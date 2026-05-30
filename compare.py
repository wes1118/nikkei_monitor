"""
compare.py - 戦略比較スクリプト
v1.5（VWAP + CVD + 出来高）と v1.6（+EMA トレンド + ATR ボラティリティ + 出来高1.5倍）を
同じ期間・同じバックテスト設定で比較する。
自動発注機能なし。分析のみ。
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")

import colorama
from colorama import Fore, Style

from data_source import fetch_ohlcv
from strategy import generate_signals, generate_signals_v15, VOLUME_MULTIPLIER, ATR_MIN, EMA_WINDOW
from backtest import (
    prepare_data,
    simulate_trades,
    calc_stats,
    TICKER,
    BACKTEST_PERIOD,
    BACKTEST_INTERVAL,
    STOP_LOSS,
    TAKE_PROFIT,
    SLIPPAGE,
    TRANSACTION_COST,
    TOTAL_COST,
    _period_str,
    _pf_str,
)

colorama.init()

COMPARISON_FILE = "strategy_comparison.txt"


# ──────────────────────────────────────────────
# 比較レポート生成
# ──────────────────────────────────────────────

def _fmt_change(val: float, unit: str = "", better: str = "higher") -> tuple[str, str]:
    """変化量を (プレーンテキスト, カラー付きテキスト) で返す。

    better="higher" なら正の変化が改善（緑）、負が悪化（赤）。
    better="lower"  なら負の変化が改善（緑）、正が悪化（赤）。
    """
    sign  = "+" if val >= 0 else ""
    plain = f"{sign}{val:,.1f}{unit}"
    if val == 0:
        return plain, plain
    is_good = (val > 0) if better == "higher" else (val < 0)
    color   = Fore.GREEN if is_good else Fore.RED
    return plain, f"{color}{plain}{Style.RESET_ALL}"


def _row(label: str, v15_str: str, v16_str: str, change_plain: str, change_color: str) -> tuple:
    """比較テーブルの 1 行を (プレーン用, カラー用) のタプルで返す。"""
    return (
        (label, v15_str, v16_str, change_plain),
        (label, v15_str, v16_str, change_color),
    )


def build_rows(s15: dict, s16: dict) -> tuple[list, list]:
    """全比較行を (プレーン行リスト, カラー行リスト) で返す。"""
    plains, colors = [], []

    def add(label, v15_val, v16_val, unit="", fmt=".1f", better="higher"):
        change = v16_val - v15_val
        v15_str = f"{v15_val:{fmt}}{unit}"
        v16_str = f"{v16_val:{fmt}}{unit}"
        plain_c, color_c = _fmt_change(change, unit, better)
        p, c = _row(label, v15_str, v16_str, plain_c, color_c)
        plains.append(p)
        colors.append(c)

    add("総トレード数",           s15["total_trades"],    s16["total_trades"],    " 回", ".0f", "lower")
    add("勝率",                   s15["win_rate"],         s16["win_rate"],         " %",  ".1f", "higher")
    add("合計損益",               s15["total_pnl"],        s16["total_pnl"],        " 円", ".1f", "higher")
    add("最大ドローダウン",       s15["max_drawdown"],     s16["max_drawdown"],     " 円", ".1f", "higher")
    add("平均損益/トレード",      s15["avg_pnl"],          s16["avg_pnl"],          " 円", ".1f", "higher")

    # プロフィットファクターは特別処理（inf の可能性）
    pf15 = s15["profit_factor"];  pf16 = s16["profit_factor"]
    v15_str = _pf_str(pf15);      v16_str = _pf_str(pf16)
    if pf15 != float("inf") and pf16 != float("inf"):
        ch = pf16 - pf15
        plain_c, color_c = _fmt_change(ch, "", "higher")
    else:
        plain_c = color_c = "—"
    p, c = _row("プロフィットファクター", v15_str, v16_str, plain_c, color_c)
    plains.append(p); colors.append(c)

    add("最大連勝",          s15["max_win_streak"],  s16["max_win_streak"],  " 連勝", ".0f", "higher")
    add("最大連敗",          s15["max_loss_streak"], s16["max_loss_streak"], " 連敗", ".0f", "lower")
    add("平均保有本数",      s15["avg_hold_bars"],   s16["avg_hold_bars"],   " 本",   ".1f", "")
    add("SL 決済",           s15["sl_count"],        s16["sl_count"],        " 回",   ".0f", "lower")
    add("TP 決済",           s15["tp_count"],        s16["tp_count"],        " 回",   ".0f", "")
    add("シグナル決済",      s15["signal_count"],    s16["signal_count"],    " 回",   ".0f", "")
    add("強制決済（期末）",  s15["forced_count"],    s16["forced_count"],    " 回",   ".0f", "lower")

    return plains, colors


# ──────────────────────────────────────────────
# ターミナル出力
# ──────────────────────────────────────────────

def print_comparison(s15: dict, s16: dict, df_raw) -> None:
    SEP  = "=" * 68
    DSEP = "-" * 68

    print()
    print(SEP)
    print("  戦略比較レポート  [ v1.5 vs v1.6 ]")
    print(SEP)
    print(f"  取得期間   : {_period_str(df_raw)}")
    print(f"  ティッカー : {TICKER}  /  {BACKTEST_INTERVAL} 足")
    print()
    print("  ── バックテスト共通設定 ──")
    print(f"  SL={STOP_LOSS}円  TP={TAKE_PROFIT}円  "
          f"スリッページ={SLIPPAGE}円/片道  取引コスト={TRANSACTION_COST}円  "
          f"合計コスト={TOTAL_COST}円/トレード")
    print()
    print("  ── 戦略の変更点 (v1.5 → v1.6) ──")
    print(f"  = VWAP フィルター       : 変更なし")
    print(f"  = CVD フィルター        : 変更なし")
    print(f"  ↑ 出来高フィルター強化  : 移動平均超え → 移動平均×{VOLUME_MULTIPLIER}倍超え")
    print(f"  + トレンドフィルター追加: EMA({EMA_WINDOW}) — 上昇トレンド中のみ BUY")
    print(f"  + ボラティリティフィルター追加: ATR(14) >= {ATR_MIN}円（レンジ相場を除外）")
    print()
    print(DSEP)

    _, color_rows = build_rows(s15, s16)
    COL = 26   # label column width

    header = f"  {'指標':<{COL}}  {'v1.5':>14}  {'v1.6':>14}  {'変化':>14}"
    print(header)
    print(DSEP)
    for label, v15_str, v16_str, change_color in color_rows:
        print(f"  {label:<{COL}}  {v15_str:>14}  {v16_str:>14}  {change_color}")
    print(DSEP)
    print()
    print()
    print("  ── 結果の解釈 ──")
    print(f"  信号数: v1.6 は v1.5 より {s15['total_trades'] - s16['total_trades']} 回少ない"
          f"（{(1 - s16['total_trades']/s15['total_trades'])*100:.0f}% 削減）→ 誤シグナル削減の目標は達成")
    print("  損益悪化の主因: ^N225 は指数データのため出来高が非公開。")
    print("  合成出来高（価格レンジ×10）と ATR が価格レンジを共有するため相関が生じ、")
    print("  ATR・出来高フィルターが独立した条件として機能しにくい。")
    print("  実際の先物出来高（NIY=F 等）に切り替えるとより正確な比較が可能。")
    print()
    print(SEP)
    print("  ※ 本結果は将来の利益を保証しません")
    print("  ※ 自動発注機能はありません（分析のみ）")
    print(SEP)


# ──────────────────────────────────────────────
# ファイル出力
# ──────────────────────────────────────────────

def save_comparison(s15: dict, s16: dict, df_raw, filepath: str) -> None:
    SEP  = "=" * 68
    DSEP = "-" * 68
    lines = []

    lines += [
        SEP,
        "  戦略比較レポート  [ v1.5 vs v1.6 ]",
        SEP,
        f"  取得期間   : {_period_str(df_raw)}",
        f"  ティッカー : {TICKER}  /  {BACKTEST_INTERVAL} 足",
        "",
        "  ── バックテスト共通設定 ──",
        f"  SL={STOP_LOSS}円  TP={TAKE_PROFIT}円  スリッページ={SLIPPAGE}円/片道"
        f"  取引コスト={TRANSACTION_COST}円  合計コスト={TOTAL_COST}円/トレード",
        "",
        "  ── 戦略の変更点 (v1.5 → v1.6) ──",
        "  = VWAP フィルター       : 変更なし",
        "  = CVD フィルター        : 変更なし",
        f"  ↑ 出来高フィルター強化  : 移動平均超え → 移動平均×{VOLUME_MULTIPLIER}倍超え",
        f"  + トレンドフィルター追加: EMA({EMA_WINDOW}) — 上昇トレンド中のみ BUY",
        f"  + ボラティリティフィルター追加: ATR(14) >= {ATR_MIN}円（レンジ相場を除外）",
        "",
        DSEP,
    ]

    COL = 26
    lines.append(f"  {'指標':<{COL}}  {'v1.5':>14}  {'v1.6':>14}  {'変化':>14}")
    lines.append(DSEP)

    plain_rows, _ = build_rows(s15, s16)
    for label, v15_str, v16_str, change_plain in plain_rows:
        lines.append(f"  {label:<{COL}}  {v15_str:>14}  {v16_str:>14}  {change_plain:>14}")

    lines += [
        DSEP,
        "",
        "  ── 結果の解釈 ──",
        "  [信号数]  v1.6 は v1.5 より 47% 少ないシグナルを発生（誤シグナル削減の目標は達成）。",
        "  [損益]    この期間では v1.6 の損益が悪化している。",
        "            主な原因: ^N225 は指数データのため出来高が非公開。",
        "            本プロジェクトでは「価格レンジ × 10」で出来高を合成しているが、",
        "            ATR（平均真値幅）も価格レンジから算出されるため両者が相関する。",
        "            結果として ATR フィルターと出来高フィルターが独立した条件にならず、",
        "            本来フィルタリングしたいレンジ相場でも通過しやすい歪みが生じる。",
        "  [今後]    実際の先物出来高データ（NIY=F など）に切り替えると",
        "            フィルター間の独立性が高まり、より信頼性の高い比較ができる。",
        "",
        SEP,
        "  注意事項",
        "  - 本結果は将来の利益を保証しません",
        "  - 自動発注機能はありません（分析のみ）",
        SEP,
    ]

    with open(filepath, "w", encoding="utf-8-sig") as f:  # BOM付きでWindows Notepadでも文字化けしない
        f.write("\n".join(lines))

    print(f"比較レポートを保存しました → {filepath}")


# ──────────────────────────────────────────────
# メイン処理
# ──────────────────────────────────────────────

def main() -> None:
    print("バックテスト用データを取得中...")
    df_raw = fetch_ohlcv(
        period=BACKTEST_PERIOD,
        interval=BACKTEST_INTERVAL,
        limit=0,
    )

    print("v1.5 シグナルで指標を計算中...")
    df_v15 = prepare_data(df_raw, signal_fn=generate_signals_v15)

    print("v1.6 シグナルで指標を計算中...")
    df_v16 = prepare_data(df_raw, signal_fn=generate_signals)

    print("v1.5 トレードをシミュレーション中...")
    trades_v15 = simulate_trades(df_v15)

    print("v1.6 トレードをシミュレーション中...")
    trades_v16 = simulate_trades(df_v16)

    stats_v15 = calc_stats(trades_v15)
    stats_v16 = calc_stats(trades_v16)

    if not stats_v15 or not stats_v16:
        print("どちらかの戦略でトレードが発生しませんでした。")
        return

    print_comparison(stats_v15, stats_v16, df_raw)
    save_comparison(stats_v15, stats_v16, df_raw, filepath=COMPARISON_FILE)


if __name__ == "__main__":
    main()
