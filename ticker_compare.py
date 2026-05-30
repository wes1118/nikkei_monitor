"""
ticker_compare.py - ティッカー比較スクリプト
^N225（インデックス・合成出来高）と NIY=F / NKD=F（先物・実出来高）などを
同じバックテスト設定で比較し、データ品質がシグナル精度に与える影響を確認する。
自動発注機能なし。分析のみ。
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")

import colorama
from colorama import Fore, Style

from data_source import fetch_ohlcv, probe_tickers, TICKER_CANDIDATES
from session_filter import filter_session, session_label, session_desc, SESSION
from backtest import (
    prepare_data,
    simulate_trades,
    calc_stats,
    BACKTEST_PERIOD,
    BACKTEST_INTERVAL,
    STOP_LOSS,
    TAKE_PROFIT,
    SLIPPAGE,
    TRANSACTION_COST,
    TOTAL_COST,
    _pf_str,
)

colorama.init()

COMPARISON_FILE  = "ticker_comparison.txt"
MIN_BARS         = 200    # バックテストに必要な最小バー数（少なすぎると統計的に無意味）
VALID_PRICE_MIN  = 5_000  # 円: これ未満ならスケール異常（USD建ての可能性）
VALID_PRICE_MAX  = 200_000


# ──────────────────────────────────────────────
# ティッカー探索と検証
# ──────────────────────────────────────────────

def probe_and_print() -> list[dict]:
    """利用可能なティッカーを探索して結果を表示し、有効なものだけ返す。"""
    print("\n候補ティッカーを探索中（5日間の5分足データで確認）...")
    probes = probe_tickers(interval=BACKTEST_INTERVAL, period="5d")

    SEP = "-" * 68
    print()
    print(SEP)
    print(f"  {'ティッカー':<10} {'名称':<30} {'状態':<10} {'バー数':>6}  {'出来高':>12}  {'平均価格':>10}")
    print(SEP)

    valid = []
    for p in probes:
        if p["available"]:
            price_ok = VALID_PRICE_MIN <= p["price_avg"] <= VALID_PRICE_MAX
            bars_ok  = p["bars"] >= 10   # プローブ用の閾値（フル60日は後で確認）

            status = "OK ✓" if price_ok else "価格異常"
            vol_str = p["volume_type"]
            price_str = f"{p['price_avg']:,.0f} 円"

            print(f"  {p['ticker']:<10} {p['name']:<30} {status:<10} {p['bars']:>6}本  {vol_str:>12}  {price_str:>10}")

            if price_ok and bars_ok:
                valid.append(p)
        else:
            err = p.get("error", "不明なエラー")[:40]
            print(f"  {p['ticker']:<10} {p['name']:<30} {'取得失敗':<10}  → {err}")

    print(SEP)
    print()
    return valid


# ──────────────────────────────────────────────
# フルバックテスト実行
# ──────────────────────────────────────────────

def run_full_backtest(ticker: str, name: str) -> dict | None:
    """指定ティッカーで 60 日間のバックテストを実行して結果を返す。"""
    print(f"  [{ticker}] {BACKTEST_PERIOD} のデータを取得してバックテストを実行中...")
    try:
        df_raw = fetch_ohlcv(
            ticker=ticker,
            period=BACKTEST_PERIOD,
            interval=BACKTEST_INTERVAL,
            limit=0,
        )
    except RuntimeError as e:
        print(f"  エラー: {e}")
        return None

    if len(df_raw) < MIN_BARS:
        print(f"  バー数が少なすぎます（{len(df_raw)} 本 < 最低 {MIN_BARS} 本）。スキップします。")
        return None

    df  = prepare_data(df_raw, session=SESSION)
    trades = simulate_trades(df)
    stats  = calc_stats(trades)

    return {
        "ticker":       ticker,
        "name":         name,
        "bars":         len(df_raw),
        "volume_type":  df_raw.attrs.get("volume_label", "不明"),
        "synthetic":    df_raw.attrs.get("synthetic_volume", True),
        "price_avg":    df_raw["close"].mean(),
        "period_start": df_raw["datetime"].iloc[0].strftime("%Y-%m-%d"),
        "period_end":   df_raw["datetime"].iloc[-1].strftime("%Y-%m-%d"),
        "stats":        stats,
        "trades":       trades,
    }


# ──────────────────────────────────────────────
# 比較表出力
# ──────────────────────────────────────────────

def _stat(result: dict, key: str, default=0):
    return result["stats"].get(key, default) if result and result.get("stats") else default


def build_comparison_lines(results: list[dict], plain: bool) -> list[str]:
    """比較表の行リストを生成する。plain=True で色なし（ファイル保存用）。"""
    def c_green(s): return s if plain else Fore.GREEN + s + Style.RESET_ALL
    def c_red(s):   return s if plain else Fore.RED   + s + Style.RESET_ALL
    def c_auto(val, s, better="higher"):
        if plain:
            return s
        if val == 0:
            return s
        good = (val > 0) if better == "higher" else (val < 0)
        return (Fore.GREEN if good else Fore.RED) + s + Style.RESET_ALL

    SEP  = "=" * 68
    DSEP = "-" * 68
    lines = []

    # ヘッダー
    lines.append(SEP)
    lines.append("  ティッカー比較レポート")
    lines.append(SEP)
    lines.append(f"  取得期間   : {BACKTEST_PERIOD}（5分足）")
    lines.append(f"  セッション : {session_label(SESSION)}  ({session_desc(SESSION)})")
    lines.append(f"  SL={STOP_LOSS}円  TP={TAKE_PROFIT}円  "
                 f"スリッページ={SLIPPAGE}円/片道  取引コスト={TRANSACTION_COST}円  "
                 f"合計コスト={TOTAL_COST}円/トレード")
    lines.append("")

    # ティッカー概要
    lines.append("  ── ティッカー概要 ──")
    for r in results:
        vol_flag = "" if r["synthetic"] else " ← 実出来高"
        lines.append(f"  [{r['ticker']}]  {r['name']}")
        lines.append(f"    取得期間  : {r['period_start']} 〜 {r['period_end']}")
        lines.append(f"    バー数    : {r['bars']:,} 本")
        lines.append(f"    平均価格  : {r['price_avg']:,.0f} 円")
        lines.append(f"    出来高    : {r['volume_type']}{vol_flag}")
    lines.append("")

    # 統計比較
    if len(results) < 2:
        lines.append("  比較対象のティッカーが 1 つしかありません。")
        lines.append("  （NIY=F などの先物ティッカーが利用できない場合、^N225 のみの結果を表示）")
        lines.append("")
        r = results[0]
        s = r["stats"]
        lines.append(f"  [{r['ticker']}] バックテスト結果:")
        lines.append(f"    総トレード数     : {s.get('total_trades',0):>4} 回")
        lines.append(f"    勝率             : {s.get('win_rate',0):>6.1f} %")
        lines.append(f"    合計損益         : {s.get('total_pnl',0):>+10,.1f} 円")
        lines.append(f"    最大ドローダウン : {s.get('max_drawdown',0):>+10,.1f} 円")
        lines.append(f"    プロフィットファクター : {_pf_str(s.get('profit_factor', 0))}")
    else:
        r0, r1 = results[0], results[1]
        s0, s1 = r0["stats"], r1["stats"]

        COL = 24
        t0  = r0["ticker"]
        t1  = r1["ticker"]
        lines.append(DSEP)
        lines.append(f"  {'指標':<{COL}}  {t0:>14}  {t1:>14}  {'変化':>14}")
        lines.append(DSEP)

        def row(label, key, unit="", fmt=".1f", better="higher"):
            v0 = _stat(r0, key)
            v1 = _stat(r1, key)
            ch = v1 - v0
            s0_ = f"{v0:{fmt}}{unit}"
            s1_ = f"{v1:{fmt}}{unit}"
            sign = "+" if ch >= 0 else ""
            ch_s = f"{sign}{ch:{fmt}}{unit}"
            ch_colored = c_auto(ch, ch_s, better)
            lines.append(f"  {label:<{COL}}  {s0_:>14}  {s1_:>14}  {ch_colored}")

        row("総トレード数",         "total_trades",    " 回", ".0f", "lower")
        row("勝率",                 "win_rate",        " %",  ".1f", "higher")
        row("合計損益",             "total_pnl",       " 円", ".1f", "higher")
        row("最大ドローダウン",     "max_drawdown",    " 円", ".1f", "higher")
        row("平均損益/トレード",    "avg_pnl",         " 円", ".1f", "higher")

        pf0 = s0.get("profit_factor", 0)
        pf1 = s1.get("profit_factor", 0)
        pf0_s = _pf_str(pf0)
        pf1_s = _pf_str(pf1)
        if pf0 != float("inf") and pf1 != float("inf"):
            ch = pf1 - pf0
            sign = "+" if ch >= 0 else ""
            ch_s = f"{sign}{ch:.2f}"
            ch_colored = c_auto(ch, ch_s, "higher")
        else:
            ch_colored = "—"
        lines.append(f"  {'プロフィットファクター':<{COL}}  {pf0_s:>14}  {pf1_s:>14}  {ch_colored}")

        row("最大連勝",            "max_win_streak",   " 連勝", ".0f", "higher")
        row("最大連敗",            "max_loss_streak",  " 連敗", ".0f", "lower")
        row("平均保有本数",         "avg_hold_bars",   " 本",   ".1f", "")
        row("SL 決済",             "sl_count",         " 回",   ".0f", "lower")
        row("TP 決済",             "tp_count",         " 回",   ".0f", "")
        lines.append(DSEP)

        # 解釈
        lines.append("")
        lines.append("  ── 結果の解釈 ──")
        lines.append(f"  [{t0}] 出来高: {r0['volume_type']}")
        lines.append(f"  [{t1}] 出来高: {r1['volume_type']}")
        real_r   = r0 if not r0["synthetic"] else (r1 if not r1["synthetic"] else None)
        synth_r  = r0 if r0["synthetic"]     else (r1 if r1["synthetic"]     else None)

        if real_r and synth_r:
            bar_ratio = real_r["bars"] / max(synth_r["bars"], 1)
            lines.append(f"  注目点:")
            lines.append(f"  ・バー数の差: {real_r['ticker']} は {real_r['bars']:,} 本、"
                         f"{synth_r['ticker']} は {synth_r['bars']:,} 本")
            if bar_ratio > 2:
                lines.append(f"    → 先物は CME の 24 時間取引データを含むため約 {bar_ratio:.0f}x 多い")
                lines.append(f"    → 日本市場時間のみに絞りたい場合は data_source.py の TICKER を変更")
            lines.append(f"  ・出来高の差: {real_r['ticker']} は実データ / {synth_r['ticker']} は合成データ")
            lines.append(f"    → 実出来高では CVD・出来高フィルターが独立した条件として機能する")
            lines.append(f"    → 合成出来高（価格レンジ×10）は ATR と相関するため、")
            lines.append(f"       ATR・出来高フィルターが独立して機能しにくい（過去比較で確認済）")
        elif not r0["synthetic"] and not r1["synthetic"]:
            lines.append("  → 両ティッカーとも実出来高データです。価格・流動性の違いを比較できます。")
        else:
            lines.append("  → 両ティッカーとも合成出来高データです。")

    lines.append("")
    lines.append(SEP)
    lines.append("  ※ 本結果は将来の利益を保証しません")
    lines.append("  ※ 自動発注機能はありません（分析のみ）")
    lines.append(SEP)

    return lines


def print_comparison(results: list[dict]) -> None:
    lines = build_comparison_lines(results, plain=False)
    print("\n" + "\n".join(lines))


def save_comparison(results: list[dict], filepath: str) -> None:
    lines = build_comparison_lines(results, plain=True)
    with open(filepath, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(lines))
    print(f"比較レポートを保存しました → {filepath}")


# ──────────────────────────────────────────────
# メイン処理
# ──────────────────────────────────────────────

def main() -> None:
    # Step 1: 利用可能なティッカーを探索
    valid_probes = probe_and_print()

    if not valid_probes:
        print("有効なティッカーが見つかりませんでした。終了します。")
        return

    # Step 2: 比較対象を選択
    # 目的: 実出来高（先物）と合成出来高（^N225 インデックス）の比較
    # → データ品質がシグナル精度に与える影響を確認するため
    futures_probes = [p for p in valid_probes if p["ticker"] != "^N225"]
    index_probe    = next((p for p in valid_probes if p["ticker"] == "^N225"), None)

    if futures_probes and index_probe:
        backtest_targets = [futures_probes[0], index_probe]   # 先物 vs インデックス
        print("  比較方針: 先物（実出来高）vs インデックス（合成出来高）")
    elif futures_probes:
        backtest_targets = futures_probes[:2]                 # 先物同士
        print("  比較方針: 先物ティッカー同士")
    else:
        backtest_targets = valid_probes[:2]
        print("  比較方針: 利用可能なティッカー同士")

    print(f"  バックテスト対象: {[p['ticker'] for p in backtest_targets]}\n")

    results = []
    for p in backtest_targets:
        result = run_full_backtest(p["ticker"], p["name"])
        if result:
            results.append(result)

    if not results:
        print("バックテスト結果が得られませんでした。")
        return

    # Step 3: 比較表を表示・保存
    print_comparison(results)
    save_comparison(results, filepath=COMPARISON_FILE)


if __name__ == "__main__":
    main()
