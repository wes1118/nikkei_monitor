"""
session_compare.py - セッション比較スクリプト
全セッション / 日中セッション / 夜間セッションの3つで同じ戦略を実行し、
取引時間帯がシグナル精度・損益に与える影響を比較する。
自動発注機能なし。分析のみ。

推奨ティッカー: NIY=F（24時間データあり・実出来高）
  → data_source.py の TICKER を "NIY=F" に変更してから実行してください。
  → ^N225 は日本市場時間のみのため、night_session データが取得できません。
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")

import colorama
from colorama import Fore, Style

from data_source import fetch_ohlcv, TICKER
from session_filter import (
    filter_session,
    session_label,
    session_desc,
    ALL_SESSION_KEYS,
)
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
    _period_str,
)

colorama.init()

COMPARISON_FILE = "session_comparison.txt"


# ──────────────────────────────────────────────
# セッションごとのバックテスト実行
# ──────────────────────────────────────────────

def run_session(df_raw, session: str) -> dict | None:
    """1つのセッションでバックテストを実行して結果を返す。
    データが空または取引ゼロの場合は None を返す。
    """
    label = session_label(session)

    # セッションフィルターを適用してバー数を確認
    filtered = filter_session(df_raw, session)
    if filtered.empty:
        print(f"  [{label}] データなし（このティッカーにはこの時間帯のデータがありません）")
        return None

    print(f"  [{label}]  {len(filtered):,} 本 → インジケーター計算・シミュレーション中...")
    try:
        df     = prepare_data(df_raw, session=session)
        trades = simulate_trades(df)
        stats  = calc_stats(trades)
    except ValueError as e:
        print(f"  [{label}] スキップ: {e}")
        return None

    if not stats:
        print(f"  [{label}] トレードなし（シグナルが発生しませんでした）")

    return {
        "session": session,
        "label":   label,
        "desc":    session_desc(session),
        "bars":    len(filtered),
        "stats":   stats,
    }


# ──────────────────────────────────────────────
# 3列比較表の生成
# ──────────────────────────────────────────────

def _stat(r: dict | None, key: str, default=0):
    """結果辞書から統計値を安全に取り出す。"""
    if r is None or not r.get("stats"):
        return None
    return r["stats"].get(key, default)


def _fmt(val, fmt=".1f", unit="", none_str="データなし"):
    """数値を書式化する。None の場合は none_str を返す。"""
    if val is None:
        return none_str
    sign = "+" if fmt.startswith("+") and val >= 0 else ""
    clean_fmt = fmt.lstrip("+")
    return f"{sign}{val:{clean_fmt}}{unit}"


def build_lines(results: list[dict | None], df_raw, plain: bool) -> list[str]:
    """比較表の行リストを生成する。plain=True で色なし（ファイル保存用）。"""

    def color(val, s, better="higher"):
        if plain or val is None:
            return s
        if val == 0:
            return s
        good = (val > 0) if better == "higher" else (val < 0)
        c = Fore.GREEN if good else Fore.RED
        return c + s + Style.RESET_ALL

    SEP  = "=" * 72
    DSEP = "-" * 72
    COL  = 22  # label column width
    W    = 16  # data column width

    # ヘッダー行
    headers = [r["label"] if r else "データなし" for r in results]

    lines = [
        SEP,
        "  セッション比較レポート",
        SEP,
        f"  ティッカー : {TICKER}  /  {BACKTEST_INTERVAL} 足",
        f"  取得期間   : {_period_str(df_raw)}（{BACKTEST_PERIOD}）",
        f"  SL={STOP_LOSS}円  TP={TAKE_PROFIT}円  スリッページ={SLIPPAGE}円/片道"
        f"  取引コスト={TRANSACTION_COST}円  合計コスト={TOTAL_COST}円/トレード",
        "",
        "  ── セッション定義 ──",
    ]
    for r in results:
        if r:
            lines.append(f"  {r['label']:<10}: {r['desc']}")
    lines += ["", DSEP]

    # テーブルヘッダー
    h_label = f"  {'指標':<{COL}}"
    h_cols  = "".join(f"  {h:>{W}}" for h in headers)
    lines.append(h_label + h_cols)
    lines.append(DSEP)

    def row(label, key, fmt=".1f", unit="", better="higher"):
        vals = [_stat(r, key) for r in results]
        strs = [_fmt(v, fmt, unit) for v in vals]

        # 変化方向の色付け（all_sessions を基準として最初の列）
        base = vals[0] if vals else None
        colored_strs = []
        for i, (v, s) in enumerate(zip(vals, strs)):
            if i == 0 or v is None or base is None:
                colored_strs.append(s)
            else:
                diff = v - base
                colored_strs.append(color(diff, s, better))

        label_part = f"  {label:<{COL}}"
        cols_part  = "".join(f"  {cs:>{W}}" for cs in colored_strs)
        lines.append(label_part + cols_part)

    # バー数（stats 外なので個別処理）
    bar_vals = [r["bars"] if r else None for r in results]
    bar_strs = [f"{v:,} 本" if v is not None else "データなし" for v in bar_vals]
    lines.append(f"  {'バー数':<{COL}}" + "".join(f"  {s:>{W}}" for s in bar_strs))

    row("総トレード数",          "total_trades",    ".0f", " 回",    "lower")
    row("勝率",                  "win_rate",         ".1f", " %",    "higher")
    row("合計損益",              "total_pnl",       "+.1f", " 円",   "higher")
    row("最大ドローダウン",      "max_drawdown",    "+.1f", " 円",   "higher")
    row("平均損益/トレード",     "avg_pnl",         "+.1f", " 円",   "higher")

    # プロフィットファクター（特別処理）
    pf_vals = [_stat(r, "profit_factor") for r in results]
    pf_strs = [_pf_str(v) if v is not None else "データなし" for v in pf_vals]
    base_pf = pf_vals[0]
    colored_pf = []
    for i, (v, s) in enumerate(zip(pf_vals, pf_strs)):
        if i == 0 or v is None or base_pf is None or v == float("inf") or base_pf == float("inf"):
            colored_pf.append(s)
        else:
            colored_pf.append(color(v - base_pf, s, "higher"))
    lines.append(f"  {'プロフィットファクター':<{COL}}"
                 + "".join(f"  {s:>{W}}" for s in colored_pf))

    row("最大連勝",             "max_win_streak",  ".0f", " 連勝",  "higher")
    row("最大連敗",             "max_loss_streak", ".0f", " 連敗",  "lower")
    row("平均保有本数",          "avg_hold_bars",   ".1f", " 本",    "")
    row("SL 決済",              "sl_count",        ".0f", " 回",    "lower")
    row("TP 決済",              "tp_count",        ".0f", " 回",    "higher")

    lines += [
        DSEP,
        "",
        "  ── 解釈のヒント ──",
        f"  ・全セッション  : CME 先物の 24 時間データを全て使用（トレード数が最大）",
        f"  ・日中セッション: 08:45〜15:15 JST（日本市場と同時刻の先物動向）",
        f"  ・夜間セッション: 16:30〜翌06:00 JST（欧米市場が主導する時間帯）",
        f"  ・色の意味（全セッションを基準）: 緑 = 改善  赤 = 悪化  無色 = 変化なし",
        f"  ・VWAP/CVD は暦日（JST 00:00）でリセット（夜間セッション単位リセットは未対応）",
        "",
        SEP,
        "  ※ 本結果は将来の利益を保証しません",
        "  ※ 自動発注機能はありません（分析のみ）",
        SEP,
    ]

    return lines


# ──────────────────────────────────────────────
# ターミナル出力 / ファイル保存
# ──────────────────────────────────────────────

def print_comparison(results: list[dict | None], df_raw) -> None:
    lines = build_lines(results, df_raw, plain=False)
    print("\n" + "\n".join(lines))


def save_comparison(results: list[dict | None], df_raw, filepath: str) -> None:
    lines = build_lines(results, df_raw, plain=True)
    with open(filepath, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(lines))
    print(f"比較レポートを保存しました → {filepath}")


# ──────────────────────────────────────────────
# メイン処理
# ──────────────────────────────────────────────

def main() -> None:
    # ^N225 を使用していると night_session でデータが少ない可能性を事前に案内
    if TICKER == "^N225":
        print()
        print("  ⚠️  注意: ^N225 は日本市場時間のみのデータです。")
        print("      night_session は 16:30〜翌06:00 JST ですが、^N225 にはその時間帯のデータがありません。")
        print("      セッション比較には NIY=F の使用を推奨します。")
        print("      → data_source.py の TICKER を 'NIY=F' に変更してください。")
        print()

    print(f"データを取得中... [{TICKER}]  {BACKTEST_PERIOD} / {BACKTEST_INTERVAL}")
    df_raw = fetch_ohlcv(
        ticker=TICKER,
        period=BACKTEST_PERIOD,
        interval=BACKTEST_INTERVAL,
        limit=0,
    )

    print(f"\n全 {len(df_raw):,} 本を取得。各セッションでバックテストを実行中...\n")

    results = []
    for session_key in ALL_SESSION_KEYS:
        result = run_session(df_raw, session_key)
        results.append(result)

    print_comparison(results, df_raw)
    save_comparison(results, df_raw, filepath=COMPARISON_FILE)


if __name__ == "__main__":
    main()
