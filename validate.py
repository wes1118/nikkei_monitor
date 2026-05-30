"""
validate.py - アウト・オブ・サンプル検証
optimize.py で発見した最良パラメーターが、
訓練に使っていない期間（検証期間）でも有効かどうかを確認する。
自動発注機能なし。分析のみ。

【なぜ必要か】
  最適化は「過去データに最もよく合う」設定を探す。
  そのデータ固有のノイズに合わせ込んでしまうと（過学習）、
  未来のデータでは同じように機能しない。
  訓練に使っていないデータ（検証期間）で同様の結果が出るかを確認することで
  過学習の有無を客観的に判断できる。

【データ分割（時系列順・重複なし）】
  ┌──────────────────── 訓練 70% ────────────────────┬── 検証 30% ──┐
  │ optimize.py が使ったデータ                        │ 今回初めて   │
  └──────────────────────────────────────────────────┴──────────────┘
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")

import numpy as np
import colorama
from colorama import Fore, Style

from data_source import fetch_ohlcv
from session_filter import filter_session, session_label, session_desc
from backtest import BACKTEST_PERIOD, BACKTEST_INTERVAL, SLIPPAGE, TRANSACTION_COST
from optimize import (
    select_ticker,
    calc_indicators,
    gen_signals,
    fast_simulate,
    quick_stats,
)

colorama.init()


# ──────────────────────────────────────────────
# 設定
# ──────────────────────────────────────────────

# optimize.py の最良パラメーター（変更する場合はここを編集）
BEST_SL         = 150    # ストップロス（円）
BEST_TP         = 400    # テイクプロフィット（円）
BEST_VOL_MULT   = 2.0    # 出来高倍率
BEST_ATR_MIN    = 40     # ATR 最小値（円）
BEST_EMA_WINDOW = 20     # EMA 窓サイズ（本）

VALIDATION_SESSION = "day_session"   # 検証対象セッション
TRAIN_RATIO        = 0.70            # 訓練期間の割合（最初の 70%）
TOTAL_COST         = 2 * SLIPPAGE + TRANSACTION_COST  # = 40 円
MIN_TRADES         = 5               # 有意な判定に必要な最低トレード数
REPORT_FILE        = "validation_report.txt"


# ──────────────────────────────────────────────
# 1 期間のバックテスト実行
# ──────────────────────────────────────────────

def run_period(df, label: str) -> dict:
    """指定期間に最良パラメーターでバックテストを実行して結果を返す。

    引数:
        df    - セッション・期間フィルター適用済み OHLCV DataFrame
        label - "訓練期間" / "検証期間" などの表示ラベル
    """
    # インジケーター計算（各期間で独立して計算 → データ漏洩なし）
    df_ind = calc_indicators(df, ema_window=BEST_EMA_WINDOW)

    # numpy 配列に変換してシグナル生成・シミュレーション
    c  = df_ind["close"].values.astype(np.float64)
    lo = df_ind["low"].values.astype(np.float64)
    hi = df_ind["high"].values.astype(np.float64)

    sigs = gen_signals(
        c,
        df_ind["vwap"].values.astype(np.float64),
        df_ind["cvd"].values.astype(np.float64),
        df_ind["volume"].values.astype(np.float64),
        df_ind["vol_avg"].values.astype(np.float64),
        df_ind["ema"].values.astype(np.float64),
        df_ind["atr"].values.astype(np.float64),
        BEST_VOL_MULT, BEST_ATR_MIN,
    )
    pnls  = fast_simulate(c, lo, hi, sigs, BEST_SL, BEST_TP)
    stats = quick_stats(pnls)

    return {
        "label": label,
        "start": df["datetime"].iloc[0].strftime("%Y-%m-%d"),
        "end":   df["datetime"].iloc[-1].strftime("%Y-%m-%d"),
        "bars":  len(df),
        "stats": stats,     # None の場合はトレード数不足
    }


# ──────────────────────────────────────────────
# ロバスト性の判定
# ──────────────────────────────────────────────

def _pf_str(pf) -> str:
    if pf is None:
        return "N/A"
    return f"{pf:.2f}" if pf != float("inf") else "∞"


def conclude(train_r: dict, val_r: dict) -> dict:
    """検証結果からロバスト性を判定する。

    判定基準:
      Robust          : 検証 PF >= 1.0 かつ損益 > 0 かつ PF 維持率 >= 70%
      Possibly Overfit: 検証 PF >= 1.0 かつ損益 > 0 だが PF 維持率 < 70%
                        または 検証 PF >= 0.85（小幅な劣化）
      Not Robust      : 検証 PF < 0.85 または損益が大幅にマイナス
      Unknown         : トレード数不足で判定不能
    """
    ts = train_r.get("stats")
    vs = val_r.get("stats")

    # トレード数不足チェック
    if vs is None:
        n = val_r["bars"]
        return {
            "key":         "unknown",
            "en":          "Unknown",
            "ja":          "判定不能",
            "color":       Fore.WHITE,
            "reason":      (
                f"検証期間のトレード数が {MIN_TRADES} 回未満です。\n"
                f"  バー数: {n} 本 / 日中セッションにシグナルが少ない可能性があります。\n"
                "  より長い期間のデータで再試行してください。"
            ),
            "recommend":   "データ期間を延ばして再検証してください。",
        }

    val_pf    = vs["profit_factor"]
    train_pf  = ts["profit_factor"] if ts else 1.0
    val_pnl   = vs["total_pnl"]
    val_trades = vs["total_trades"]

    val_pf_n   = min(val_pf,   9999) if val_pf   != float("inf") else 9999
    train_pf_n = min(train_pf, 9999) if train_pf != float("inf") else 9999
    pf_ratio   = val_pf_n / train_pf_n if train_pf_n > 0 else 0

    if val_pf >= 1.0 and val_pnl > 0 and pf_ratio >= 0.70:
        return {
            "key":       "robust",
            "en":        "Robust",
            "ja":        "ロバスト",
            "color":     Fore.GREEN,
            "reason":    (
                f"  検証 PF = {_pf_str(val_pf)}（基準: >= 1.0）✓\n"
                f"  検証損益 = {val_pnl:+,.0f} 円（基準: > 0）✓\n"
                f"  PF 維持率 = {pf_ratio:.0%}（訓練 PF {_pf_str(train_pf)} → 検証 PF {_pf_str(val_pf)}）✓\n"
                "  訓練期間外でも安定した利益が出ており、過学習の兆候は低いです。"
            ),
            "recommend": (
                "このパラメーターは実際の取引での適用を検討できます。\n"
                "  ただし、追加の期間でも継続して検証することを推奨します。"
            ),
        }

    elif val_pf >= 1.0 and val_pnl > 0:
        return {
            "key":       "possibly_overfit",
            "en":        "Possibly Overfit",
            "ja":        "過学習の可能性あり",
            "color":     Fore.YELLOW,
            "reason":    (
                f"  検証 PF = {_pf_str(val_pf)}（>= 1.0）✓ 検証損益プラス ✓\n"
                f"  PF 維持率 = {pf_ratio:.0%}（基準: >= 70% → {pf_ratio:.0%} で未達）✗\n"
                "  検証期間でも利益はありますが、訓練期間より大幅にパフォーマンスが低下しています。"
            ),
            "recommend": (
                "別の時間帯・別の期間長でも追加検証を行ってください。\n"
                "  PF 維持率が低い場合、パラメーターをやや緩めて再最適化することも有効です。"
            ),
        }

    elif val_pf >= 0.85:
        return {
            "key":       "possibly_overfit",
            "en":        "Possibly Overfit",
            "ja":        "過学習の可能性あり",
            "color":     Fore.YELLOW,
            "reason":    (
                f"  検証 PF = {_pf_str(val_pf)}（0.85 以上 1.0 未満）\n"
                f"  検証損益 = {val_pnl:+,.0f} 円（プロフィットファクター 1.0 に届かず）\n"
                f"  PF 維持率 = {pf_ratio:.0%}  訓練期間に比べて小幅な劣化です。"
            ),
            "recommend": (
                "パラメーターの再調整または追加期間での検証が必要です。\n"
                "  optimize.py を再実行して、より安定したパラメーターを探すことを検討してください。"
            ),
        }

    else:
        return {
            "key":       "not_robust",
            "en":        "Not Robust",
            "ja":        "非ロバスト",
            "color":     Fore.RED,
            "reason":    (
                f"  検証 PF = {_pf_str(val_pf)}（基準: >= 0.85 → 未達）✗\n"
                f"  検証損益 = {val_pnl:+,.0f} 円\n"
                f"  PF 維持率 = {pf_ratio:.0%}  訓練期間のパフォーマンスを大幅に下回っています。"
            ),
            "recommend": (
                "このパラメーターの実使用は推奨しません。\n"
                "  optimize.py を再実行して別のパラメーターを探してください。\n"
                "  より長い訓練期間・より広いパラメーターグリッドも有効です。"
            ),
        }


# ──────────────────────────────────────────────
# 出力ライン生成
# ──────────────────────────────────────────────

def build_lines(ticker: str, n_total: int, n_train: int,
                train_r: dict, val_r: dict,
                conclusion: dict, plain: bool) -> list[str]:
    """比較表と結論を行リストで返す。plain=True で色なし（ファイル保存用）。"""

    def col(val, s, better="higher"):
        """変化量に色を付ける（plain の場合は無色）。"""
        if plain or val == 0 or val is None:
            return s
        good = (val > 0) if better == "higher" else (val < 0)
        return (Fore.GREEN if good else Fore.RED) + s + Style.RESET_ALL

    SEP  = "=" * 68
    DSEP = "-" * 68
    ts   = train_r.get("stats") or {}
    vs   = val_r.get("stats")   or {}

    # ── ヘッダー ──────────────────────────────
    lines = [
        SEP,
        "  アウト・オブ・サンプル検証レポート",
        SEP,
        f"  ティッカー : {ticker}  /  {session_label(VALIDATION_SESSION)}"
        f"  ({session_desc(VALIDATION_SESSION)})",
        "",
        "  ── 使用パラメーター（optimize.py の最良値） ──",
        f"  ストップロス              : {BEST_SL:>5} 円",
        f"  テイクプロフィット        : {BEST_TP:>5} 円",
        f"  出来高倍率  (vol_mult)    : {BEST_VOL_MULT:>5.1f} 倍",
        f"  ATR 最小値  (atr_min)     : {BEST_ATR_MIN:>5} 円",
        f"  EMA 窓サイズ (ema_window) : {BEST_EMA_WINDOW:>5} 本",
        "",
        "  ── データ分割 ──",
        (
            f"  全バー数 {n_total:,} 本 → "
            f"訓練 {n_train:,} 本 ({TRAIN_RATIO:.0%}) +"
            f" 検証 {n_total - n_train:,} 本 ({1-TRAIN_RATIO:.0%})"
        ),
        f"  訓練期間 : {train_r['start']} 〜 {train_r['end']}  ({train_r['bars']:,} 本)",
        f"  検証期間 : {val_r['start']} 〜 {val_r['end']}  ({val_r['bars']:,} 本)",
        f"  {'─' * 50}",
        f"  ├{'─'*34}訓練 70%{'─'*8}┤{'─'*13}検証 30%{'─'*3}┤",
        f"  {train_r['start']:<20}{'':>15}{val_r['start']:<12}{val_r['end']:>10}",
        "",
    ]

    # ── 比較テーブル ──────────────────────────
    COL = 26; W = 16

    header = f"  {'指標':<{COL}}  {'訓練期間 (70%)':>{W}}  {'検証期間 (30%)':>{W}}  {'変化':>{W}}"
    lines += [DSEP, header, DSEP]

    def row(label, t_val, v_val, unit="", fmt=".1f", better="higher", neutral=False):
        """比較行を1行生成する。"""
        t_s = f"{t_val:{fmt}}{unit}" if t_val is not None else "データなし"
        v_s = f"{v_val:{fmt}}{unit}" if v_val is not None else "データなし"
        if t_val is not None and v_val is not None and not neutral:
            diff = v_val - t_val
            sign = "+" if diff >= 0 else ""
            ch_s = f"{sign}{diff:{fmt}}{unit}"
            ch_colored = col(diff, ch_s, better)
        else:
            ch_s = ch_colored = "—"
        lines.append(
            f"  {label:<{COL}}  {t_s:>{W}}  {v_s:>{W}}  {ch_colored}"
        )

    def row_pf(label, t_pf, v_pf):
        """プロフィットファクター専用の行（∞ 対応）。"""
        t_s = _pf_str(t_pf)
        v_s = _pf_str(v_pf)
        if t_pf is not None and v_pf is not None \
                and t_pf != float("inf") and v_pf != float("inf"):
            diff    = v_pf - t_pf
            sign    = "+" if diff >= 0 else ""
            ch_s    = f"{sign}{diff:.2f}"
            ch_colored = col(diff, ch_s, "higher")
        else:
            ch_s = ch_colored = "—"
        lines.append(
            f"  {label:<{COL}}  {t_s:>{W}}  {v_s:>{W}}  {ch_colored}"
        )

    # バー数（中立）
    t_bars = train_r["bars"]
    v_bars = val_r["bars"]
    lines.append(
        f"  {'バー数':<{COL}}  {t_bars:>{W},} 本  {v_bars:>{W},} 本  {'—':>{W}}"
    )

    t_trades = ts.get("total_trades")
    v_trades = vs.get("total_trades")
    row("総トレード数",       t_trades,              v_trades,              " 回", ".0f", neutral=True)
    row("勝率",               ts.get("win_rate"),     vs.get("win_rate"),     " %",  ".1f", "higher")
    row("合計損益",           ts.get("total_pnl"),    vs.get("total_pnl"),    " 円", "+.1f", "higher")
    row("最大ドローダウン",   ts.get("max_drawdown"), vs.get("max_drawdown"), " 円", "+.1f", "higher")
    row_pf("プロフィットファクター", ts.get("profit_factor"), vs.get("profit_factor"))

    lines.append(DSEP)

    # ── 結論 ────────────────────────────────
    c_key   = conclusion["en"]
    c_ja    = conclusion["ja"]
    c_color = conclusion["color"]
    c_box   = f"★  {c_key}  /  {c_ja}  ★"

    lines += ["", "  ── 結論 ──"]
    if plain:
        lines.append(f"  {c_box}")
    else:
        lines.append(f"  {c_color}{c_box}{Style.RESET_ALL}")

    lines += [
        "",
        *[f"  {ln}" for ln in conclusion["reason"].splitlines()],
        "",
        "  【推奨アクション】",
        *[f"  {ln}" for ln in conclusion["recommend"].splitlines()],
        "",
        SEP,
        "  ※ 過去データを使ったシミュレーションです。将来の利益を保証しません。",
        "  ※ 自動発注機能はありません（分析のみ）。",
        SEP,
    ]

    return lines


# ──────────────────────────────────────────────
# ターミナル出力 / ファイル保存
# ──────────────────────────────────────────────

def print_report(ticker, n_total, n_train, train_r, val_r, conclusion) -> None:
    lines = build_lines(ticker, n_total, n_train, train_r, val_r, conclusion, plain=False)
    print("\n" + "\n".join(lines))


def save_report(ticker, n_total, n_train, train_r, val_r, conclusion, filepath) -> None:
    lines = build_lines(ticker, n_total, n_train, train_r, val_r, conclusion, plain=True)
    with open(filepath, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(lines))
    print(f"検証レポートを保存しました → {filepath}")


# ──────────────────────────────────────────────
# メイン処理
# ──────────────────────────────────────────────

def main() -> None:
    print()
    print("アウト・オブ・サンプル検証を開始します")
    print(f"  セッション : {session_label(VALIDATION_SESSION)}"
          f"  ({session_desc(VALIDATION_SESSION)})")
    print(f"  分割比率   : 訓練 {TRAIN_RATIO:.0%}  /  検証 {1-TRAIN_RATIO:.0%}")
    print(f"  パラメーター: SL={BEST_SL}  TP={BEST_TP}  "
          f"倍率={BEST_VOL_MULT}  ATR={BEST_ATR_MIN}  EMA={BEST_EMA_WINDOW}")
    print()

    # Step 1: ティッカー選択（NIY=F 優先）
    ticker = select_ticker()

    # Step 2: データ取得
    print(f"\nデータを取得中... [{ticker}]")
    df_raw = fetch_ohlcv(
        ticker=ticker,
        period=BACKTEST_PERIOD,
        interval=BACKTEST_INTERVAL,
        limit=0,
    )

    # Step 3: セッションフィルター
    df_session = filter_session(df_raw, VALIDATION_SESSION)
    if df_session.empty:
        print("エラー: セッションフィルター後にデータがありません。")
        return

    n_total = len(df_session)
    n_train = int(n_total * TRAIN_RATIO)
    n_val   = n_total - n_train

    print(f"\n  全バー数: {n_total:,} 本")
    print(f"  訓練期間: 最初の {n_train:,} 本 ({TRAIN_RATIO:.0%})")
    print(f"  検証期間: 最後の {n_val:,} 本 ({1-TRAIN_RATIO:.0%})")

    # Step 4: 期間分割
    df_train = df_session.iloc[:n_train].reset_index(drop=True)
    df_val   = df_session.iloc[n_train:].reset_index(drop=True)

    # Step 5: 各期間でバックテスト実行
    print("\n訓練期間でバックテストを実行中...")
    train_r = run_period(df_train, "訓練期間")
    ts = train_r["stats"]
    if ts:
        print(f"  → {ts['total_trades']} 回  勝率 {ts['win_rate']:.1f}%  "
              f"損益 {ts['total_pnl']:+,.0f}円  PF {_pf_str(ts['profit_factor'])}")
    else:
        print(f"  → トレード数不足（{MIN_TRADES} 回未満）")

    print("\n検証期間でバックテストを実行中...")
    val_r = run_period(df_val, "検証期間")
    vs = val_r["stats"]
    if vs:
        print(f"  → {vs['total_trades']} 回  勝率 {vs['win_rate']:.1f}%  "
              f"損益 {vs['total_pnl']:+,.0f}円  PF {_pf_str(vs['profit_factor'])}")
    else:
        print(f"  → トレード数不足（{MIN_TRADES} 回未満）")

    # Step 6: ロバスト性の判定
    conclusion = conclude(train_r, val_r)

    # Step 7: 出力
    print_report(ticker, n_total, n_train, train_r, val_r, conclusion)
    save_report(ticker, n_total, n_train, train_r, val_r, conclusion, filepath=REPORT_FILE)


if __name__ == "__main__":
    main()
