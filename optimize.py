"""
optimize.py - パラメーター最適化（グリッドサーチ）
複数のパラメーター組み合わせでバックテストを実行し、最良設定を探す。
自動発注機能なし。分析のみ。

【高速化の仕組み】
  1. EMA 窓サイズが変わる時だけ指標を再計算（3回のみ）
  2. シグナル生成は numpy のベクトル演算で一括処理（27回）
  3. シミュレーションは numpy 配列を直接参照（pandas の iterrows より高速）

【推奨環境】
  - ティッカー: NIY=F（利用不可なら data_source.py の TICKER にフォールバック）
  - セッション: day_session（日中セッション 08:45〜15:15 JST）
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")

import time
import numpy as np
import pandas as pd
from tabulate import tabulate
import colorama
from colorama import Fore, Style

from data_source import fetch_ohlcv, TICKER
from session_filter import filter_session, session_label, session_desc
from indicators import (
    calculate_vwap, calculate_cvd,
    calculate_ema, calculate_volume_avg, calculate_atr,
)
from backtest import BACKTEST_PERIOD, BACKTEST_INTERVAL, SLIPPAGE, TRANSACTION_COST

colorama.init()


# ──────────────────────────────────────────────
# 最適化設定
# ──────────────────────────────────────────────

PREFERRED_TICKER     = "NIY=F"         # 優先ティッカー（実出来高・24時間データ）
OPTIMIZATION_SESSION = "day_session"   # 最適化対象セッション
MIN_TRADES           = 5               # この件数未満の組み合わせはスキップ
TOP_N                = 20              # レポートに保存する上位件数
REPORT_FILE          = "optimization_report.txt"

TOTAL_COST = 2 * SLIPPAGE + TRANSACTION_COST  # 40 円 / トレード（固定）

# ── パラメーターグリッド ──────────────────────
SL_VALUES       = [100, 150, 200]       # ストップロス（円）
TP_VALUES       = [200, 300, 400]       # テイクプロフィット（円）
VOL_MULT_VALUES = [1.2, 1.5, 2.0]      # 出来高フィルター倍率
ATR_MIN_VALUES  = [20,  30,  40]        # ATR 最小値（円）
EMA_WIN_VALUES  = [10,  20,  30]        # EMA 窓サイズ（本）

TOTAL_COMBINATIONS = (
    len(SL_VALUES) * len(TP_VALUES) *
    len(VOL_MULT_VALUES) * len(ATR_MIN_VALUES) * len(EMA_WIN_VALUES)
)   # = 3^5 = 243 通り


# ──────────────────────────────────────────────
# ティッカー選択
# ──────────────────────────────────────────────

def select_ticker() -> str:
    """NIY=F が利用可能な場合はそれを使う（実出来高あり）。
    利用できない場合は data_source.py の TICKER にフォールバックする。
    """
    print("  NIY=F の利用可能性を確認中...", end="", flush=True)
    try:
        df = fetch_ohlcv(
            ticker=PREFERRED_TICKER,
            period="5d",
            interval="5m",
            limit=0,
            verbose=False,
        )
        if len(df) >= 50:
            vol = "実データ" if not df.attrs.get("synthetic_volume") else "合成データ"
            print(f" 利用可能 ✓  （{len(df)} 本 / 出来高: {vol}）")
            return PREFERRED_TICKER
    except Exception:
        pass
    print(f" 利用不可 → {TICKER} を使用します")
    return TICKER


# ──────────────────────────────────────────────
# インジケーター計算（EMA 窓サイズが可変）
# ──────────────────────────────────────────────

def calc_indicators(df: pd.DataFrame, ema_window: int) -> pd.DataFrame:
    """セッションフィルター適用済みデータに全インジケーターを計算する。
    EMA 窓サイズはパラメーターグリッドから渡される。
    VWAP/CVD/EMA は日次リセット、vol_avg/ATR は通しで計算する。
    """
    df = df.copy()
    df["_date"] = df["datetime"].dt.date

    day_groups = []
    for _, day_df in df.groupby("_date", sort=True):
        day_df = day_df.copy().reset_index(drop=True)
        day_df = calculate_vwap(day_df)
        day_df = calculate_cvd(day_df)
        day_df = calculate_ema(day_df, window=ema_window)
        day_groups.append(day_df)

    result = pd.concat(day_groups).reset_index(drop=True)
    result  = calculate_volume_avg(result, window=5)
    result  = calculate_atr(result, period=14)
    return result.drop(columns=["_date"])


# ──────────────────────────────────────────────
# シグナル生成（numpy ベクトル演算）
# ──────────────────────────────────────────────

def gen_signals(closes, vwap, cvd, vol, vol_avg, ema, atr,
                vol_mult: float, atr_min: float) -> np.ndarray:
    """シグナルを numpy ベクトル演算で一括生成する。
    戻り値: int8 配列（1=買い / -1=売り / 0=見送り）
    """
    buy_cond = (
        (closes > vwap) & (cvd > 0) &
        (vol > vol_avg * vol_mult) &
        (closes > ema) & (atr >= atr_min)
    )
    sell_cond = (
        (closes < vwap) & (cvd < 0) &
        (vol > vol_avg * vol_mult) &
        (closes < ema) & (atr >= atr_min)
    )
    signals = np.zeros(len(closes), dtype=np.int8)
    signals[buy_cond]  =  1   # 買い
    signals[sell_cond] = -1   # 売り
    return signals


# ──────────────────────────────────────────────
# トレードシミュレーション（numpy 直接参照）
# ──────────────────────────────────────────────

def fast_simulate(closes, lows, highs, signals,
                  sl: float, tp: float) -> list[float]:
    """numpy 配列を直接参照してトレードをシミュレーションする。
    pandas の iterrows() を使わないため大幅に高速化されている。

    決済優先順位:
      1. ストップロス（安値が SL レベルを下回った）
      2. テイクプロフィット（高値が TP レベルを上回った）
      3. 売りシグナル
      4. 期末強制決済

    戻り値: 各トレードの純損益リスト（コスト控除済み）
    """
    pnls      = []
    pos_price = None
    pos_sl    = None
    pos_tp    = None
    n         = len(closes)

    for i in range(n):
        if pos_price is None:
            if signals[i] == 1:               # 買いシグナルでエントリー
                pos_price = closes[i]
                pos_sl    = pos_price - sl
                pos_tp    = pos_price + tp
        else:
            if lows[i] <= pos_sl:             # SL ヒット
                pnls.append(pos_sl - pos_price - TOTAL_COST)
                pos_price = None
            elif highs[i] >= pos_tp:          # TP ヒット
                pnls.append(pos_tp - pos_price - TOTAL_COST)
                pos_price = None
            elif signals[i] == -1:            # 売りシグナルで決済
                pnls.append(closes[i] - pos_price - TOTAL_COST)
                pos_price = None

    if pos_price is not None:                 # 期末強制決済
        pnls.append(closes[-1] - pos_price - TOTAL_COST)

    return pnls


# ──────────────────────────────────────────────
# 統計計算（最適化用・軽量版）
# ──────────────────────────────────────────────

def quick_stats(pnls: list[float]) -> dict | None:
    """ランキングに必要な最小統計だけを計算する。
    トレード数が MIN_TRADES 未満の場合は None を返す。
    """
    if len(pnls) < MIN_TRADES:
        return None

    n_wins       = sum(1 for p in pnls if p > 0)
    total_pnl    = sum(pnls)
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss   = abs(sum(p for p in pnls if p < 0))

    # 最大ドローダウン
    cum = 0.0; peak = 0.0; max_dd = 0.0
    for p in pnls:
        cum += p
        if cum > peak:
            peak = cum
        dd = cum - peak
        if dd < max_dd:
            max_dd = dd

    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    return {
        "total_trades":  len(pnls),
        "win_rate":      n_wins / len(pnls) * 100,
        "total_pnl":     total_pnl,
        "max_drawdown":  max_dd,
        "profit_factor": pf,
    }


# ──────────────────────────────────────────────
# グリッドサーチ
# ──────────────────────────────────────────────

def run_grid_search(df_session: pd.DataFrame) -> list[dict]:
    """全パラメーター組み合わせでバックテストを実行して結果リストを返す。"""
    results = []
    count   = 0
    start_t = time.time()

    for ema_window in EMA_WIN_VALUES:
        # EMA が変わる時だけ指標を再計算（3回のみ）
        df_ind = calc_indicators(df_session, ema_window)

        # numpy 配列に変換（ループ内の pandas アクセスを排除）
        closes  = df_ind["close"].values.astype(np.float64)
        lows    = df_ind["low"].values.astype(np.float64)
        highs   = df_ind["high"].values.astype(np.float64)
        vwap    = df_ind["vwap"].values.astype(np.float64)
        cvd     = df_ind["cvd"].values.astype(np.float64)
        vol     = df_ind["volume"].values.astype(np.float64)
        vol_avg = df_ind["vol_avg"].values.astype(np.float64)
        ema     = df_ind["ema"].values.astype(np.float64)
        atr     = df_ind["atr"].values.astype(np.float64)

        for vol_mult in VOL_MULT_VALUES:
            for atr_min in ATR_MIN_VALUES:
                # シグナルをベクトル演算で生成（27回）
                sigs = gen_signals(
                    closes, vwap, cvd, vol, vol_avg, ema, atr,
                    vol_mult, atr_min,
                )

                for sl in SL_VALUES:
                    for tp in TP_VALUES:
                        count += 1

                        pnls  = fast_simulate(closes, lows, highs, sigs, sl, tp)
                        stats = quick_stats(pnls)

                        if stats:
                            results.append({
                                "sl":         sl,
                                "tp":         tp,
                                "vol_mult":   vol_mult,
                                "atr_min":    atr_min,
                                "ema_window": ema_window,
                                **stats,
                            })

                        # プログレス表示（10件ごと更新）
                        if count % 10 == 0 or count == TOTAL_COMBINATIONS:
                            elapsed = time.time() - start_t
                            eta = (elapsed / count) * (TOTAL_COMBINATIONS - count)
                            print(
                                f"\r  [{count:>3}/{TOTAL_COMBINATIONS}] "
                                f"{count/TOTAL_COMBINATIONS*100:4.0f}%  "
                                f"経過: {elapsed:4.1f}秒  残り: {eta:4.1f}秒",
                                end="",
                                flush=True,
                            )

    elapsed = time.time() - start_t
    print(f"\r  [{TOTAL_COMBINATIONS}/{TOTAL_COMBINATIONS}] 100%  合計: {elapsed:.1f}秒  "
          f"有効結果: {len(results)} 件 / {TOTAL_COMBINATIONS} 通り        ")
    return results


# ──────────────────────────────────────────────
# ランク付け
# ──────────────────────────────────────────────

def rank_results(results: list[dict]) -> list[dict]:
    """プロフィットファクター → 最大ドローダウン → 合計損益 の優先順でソートする。

    ソートキーの説明:
        pf_key  : PF が高いほど良い → 降順（key を負にして昇順ソート）
        dd_key  : max_drawdown は負の値。0 に近いほど良い →
                  -max_drawdown が小さいほど良い（昇順）
        pnl_key : 損益が高いほど良い → 降順（key を負にして昇順ソート）
    """
    def _key(r):
        pf = min(r["profit_factor"], 9999) if r["profit_factor"] != float("inf") else 9999
        return (
            -pf,                   # PF 降順
            -r["max_drawdown"],    # DD 少ない方（0 に近い方）が先
            -r["total_pnl"],       # P&L 降順
        )

    results.sort(key=_key)
    for i, r in enumerate(results, 1):
        r["rank"] = i
    return results


# ──────────────────────────────────────────────
# ターミナル出力
# ──────────────────────────────────────────────

def _pf_str(pf: float) -> str:
    return f"{pf:.2f}" if pf != float("inf") else "∞"


def print_best(best: dict, ticker: str, n_bars: int) -> None:
    """最優秀パラメーターと結果をターミナルに表示する。"""
    SEP = "=" * 64
    pf  = best["profit_factor"]
    pnl_color = Fore.GREEN if best["total_pnl"] >= 0 else Fore.RED
    pf_color  = Fore.GREEN if (pf >= 1.0 or pf == float("inf")) else Fore.RED

    print()
    print(SEP)
    print(f"  パラメーター最適化結果  [ {ticker} / {OPTIMIZATION_SESSION} ]")
    print(SEP)
    print(f"  検証組み合わせ数 : {TOTAL_COMBINATIONS} 通り")
    print(f"  使用バー数       : {n_bars:,} 本（日中セッション）")
    print()
    print("  ── 最優秀パラメーター（プロフィットファクター優先） ──")
    print(f"  ストップロス              : {best['sl']:>5} 円")
    print(f"  テイクプロフィット        : {best['tp']:>5} 円")
    print(f"  出来高倍率  (vol_mult)    : {best['vol_mult']:>5.1f} 倍")
    print(f"  ATR 最小値  (atr_min)     : {best['atr_min']:>5} 円")
    print(f"  EMA 窓サイズ (ema_window) : {best['ema_window']:>5} 本")
    print()
    print("  ── バックテスト結果 ──")
    print(f"  総トレード数       : {best['total_trades']:>4} 回")
    print(f"  勝率               : {best['win_rate']:>6.1f} %")
    print(f"  合計損益           : {pnl_color}{best['total_pnl']:>+10,.1f} 円{Style.RESET_ALL}")
    print(f"  最大ドローダウン   : {Fore.RED}{best['max_drawdown']:>+10,.1f} 円{Style.RESET_ALL}")
    print(f"  プロフィットファクター : {pf_color}{_pf_str(pf)}{Style.RESET_ALL}")
    print()
    print(SEP)
    print("  ⚠️  過去データへの最適化です。将来の利益を保証しません（過学習に注意）。")
    print("  ⚠️  自動発注機能はありません（分析のみ）。")
    print(SEP)


def print_top3(ranked: list[dict]) -> None:
    """上位3件をコンパクトに表示する。"""
    print()
    print("  ── 上位 3 件サマリー ──")
    for r in ranked[:3]:
        pf    = r["profit_factor"]
        color = Fore.GREEN if (pf >= 1.0 or pf == float("inf")) else Fore.RED
        print(
            f"  [{r['rank']:>2}位]  "
            f"SL={r['sl']:>3}  TP={r['tp']:>3}  "
            f"倍率={r['vol_mult']:.1f}  ATR={r['atr_min']:>2}  EMA={r['ema_window']:>2}  →  "
            f"PF={color}{_pf_str(pf)}{Style.RESET_ALL}  "
            f"DD={r['max_drawdown']:>+6,.0f}円  "
            f"損益={r['total_pnl']:>+7,.0f}円"
        )
    print()


# ──────────────────────────────────────────────
# レポートファイル保存
# ──────────────────────────────────────────────

def save_report(ranked: list[dict], ticker: str, n_bars: int, filepath: str) -> None:
    """上位 TOP_N 件を optimization_report.txt に保存する。"""
    SEP = "=" * 80
    top = ranked[:TOP_N]

    lines = [
        SEP,
        f"  パラメーター最適化レポート  [ {ticker} / {OPTIMIZATION_SESSION} ]",
        SEP,
        f"  検証組み合わせ数 : {TOTAL_COMBINATIONS} 通り",
        f"  使用バー数       : {n_bars:,} 本（日中セッション）",
        f"  有効結果         : {len(ranked)} 件（{MIN_TRADES} 回未満のトレードを除外）",
        f"  ソート基準       : プロフィットファクター → 最大ドローダウン → 合計損益",
        "",
        "  ── パラメーターグリッド ──",
        f"  ストップロス         : {SL_VALUES}",
        f"  テイクプロフィット   : {TP_VALUES}",
        f"  出来高倍率           : {VOL_MULT_VALUES}",
        f"  ATR 最小値           : {ATR_MIN_VALUES}",
        f"  EMA 窓サイズ         : {EMA_WIN_VALUES}",
        f"  固定コスト（往復）   : {TOTAL_COST} 円/トレード"
        f"（スリッページ {SLIPPAGE}円×2 + 取引コスト {TRANSACTION_COST}円）",
        "",
        f"  ── 上位 {len(top)} 件 ──",
    ]

    headers = [
        "順位", "SL", "TP", "倍率", "ATR", "EMA",
        "取引数", "勝率%", "合計損益(円)", "最大DD(円)", "PF",
    ]
    rows = [
        [
            r["rank"],
            r["sl"], r["tp"],
            f"{r['vol_mult']:.1f}", r["atr_min"], r["ema_window"],
            r["total_trades"],
            f"{r['win_rate']:.1f}",
            f"{r['total_pnl']:+,.0f}",
            f"{r['max_drawdown']:+,.0f}",
            _pf_str(r["profit_factor"]),
        ]
        for r in top
    ]

    lines.append(
        tabulate(rows, headers=headers, tablefmt="simple",
                 stralign="right", numalign="right")
    )

    lines += [
        "",
        SEP,
        "  ⚠️  注意事項",
        "  - この結果は過去データへの最適化です。将来の利益を保証しません。",
        "  - パラメーターを過度に最適化すると「過学習（カーブフィッティング）」の",
        "    リスクがあります。最良値を盲目的に採用せず、複数期間で検証してください。",
        "  - 自動発注機能はありません（分析のみ）。",
        SEP,
    ]

    with open(filepath, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(lines))

    print(f"最適化レポートを保存しました → {filepath}")


# ──────────────────────────────────────────────
# メイン処理
# ──────────────────────────────────────────────

def main() -> None:
    print()
    print(f"パラメーター最適化を開始します")
    print(f"  組み合わせ数 : {TOTAL_COMBINATIONS} 通り  "
          f"（{len(SL_VALUES)}×{len(TP_VALUES)}×{len(VOL_MULT_VALUES)}"
          f"×{len(ATR_MIN_VALUES)}×{len(EMA_WIN_VALUES)}）")
    print(f"  セッション   : {session_label(OPTIMIZATION_SESSION)}"
          f"  （{session_desc(OPTIMIZATION_SESSION)}）")
    print()

    # Step 1: ティッカー選択
    ticker = select_ticker()

    # Step 2: データ取得
    print(f"\nデータを取得中... [{ticker}]")
    df_raw = fetch_ohlcv(
        ticker=ticker,
        period=BACKTEST_PERIOD,
        interval=BACKTEST_INTERVAL,
        limit=0,
    )

    # Step 3: セッションフィルター（最適化全体で共通）
    df_session = filter_session(df_raw, OPTIMIZATION_SESSION)
    if df_session.empty:
        print("エラー: セッションフィルター後にデータがありません。")
        print("  → NIY=F を使用し、day_session で再試行してください。")
        return

    n_bars = len(df_session)
    print(f"\n{session_label(OPTIMIZATION_SESSION)}: {n_bars:,} 本  "
          f"グリッドサーチを実行中...\n")

    # Step 4: グリッドサーチ
    results = run_grid_search(df_session)

    if not results:
        print("有効な結果がありません。"
              f"トレード数が {MIN_TRADES} 回未満の組み合わせしかありませんでした。")
        return

    # Step 5: ランク付け・出力
    ranked = rank_results(results)
    print_best(ranked[0], ticker, n_bars)
    print_top3(ranked)
    save_report(ranked, ticker, n_bars, filepath=REPORT_FILE)


if __name__ == "__main__":
    main()
