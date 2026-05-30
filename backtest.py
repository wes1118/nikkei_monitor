"""
backtest.py - シンプルバックテスト
過去データに BUY/SELL シグナルを適用して損益をシミュレーションする。
自動発注機能なし。分析のみ。
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd
from tabulate import tabulate
import colorama
from colorama import Fore, Style

from data_source import fetch_ohlcv
from indicators import calculate_vwap, calculate_volume_avg, calculate_cvd
from strategy import generate_signals

colorama.init()

TICKER            = "^N225"
BACKTEST_PERIOD   = "60d"    # yfinance の 5 分足は最大 60 日まで無料取得可能
BACKTEST_INTERVAL = "5m"
VOL_WINDOW        = 5        # 出来高移動平均の期間（main.py と合わせる）
REPORT_FILE       = "backtest_report.txt"


# ──────────────────────────────────────────────
# データ準備（インジケーター計算）
# ──────────────────────────────────────────────

def prepare_data(df: pd.DataFrame) -> pd.DataFrame:
    """VWAP と CVD を日付ごとにリセットしてから全インジケーターとシグナルを計算する。

    VWAP と CVD はセッション内で累積するインジケーターのため、
    日をまたいで計算すると初日の値が後続日に引きずられ不正確になる。
    そのため日付ごとにグループ化して個別に計算し直す。
    """
    df = df.copy()
    df["_date"] = df["datetime"].dt.date

    day_groups = []
    for _, day_df in df.groupby("_date", sort=True):
        day_df = day_df.copy().reset_index(drop=True)
        day_df = calculate_vwap(day_df)
        day_df = calculate_cvd(day_df)
        day_groups.append(day_df)

    result = pd.concat(day_groups).reset_index(drop=True)

    # 出来高移動平均は日をまたいでも自然なローリング計算でよい
    result = calculate_volume_avg(result, window=VOL_WINDOW)
    result = generate_signals(result)

    return result.drop(columns=["_date"])


# ──────────────────────────────────────────────
# トレードシミュレーション
# ──────────────────────────────────────────────

def simulate_trades(df: pd.DataFrame) -> list:
    """BUY シグナルでエントリー、SELL シグナルでエグジットするロング専用シミュレーション。

    ルール:
        - ポジションなし + BUY シグナル → その終値でロングエントリー
        - ポジションあり + SELL シグナル → その終値でエグジット
        - ポジションなし + SELL シグナル → 無視（空売りなし）
        - データ末尾までポジションが残った場合 → 最終バーの終値で強制決済
    """
    trades = []
    position = None  # None = フラット、dict = ポジション保有中

    for _, row in df.iterrows():
        if position is None and row["signal"] == "買い":
            position = {
                "entry_time":  row["datetime"],
                "entry_price": row["close"],
            }
        elif position is not None and row["signal"] == "売り":
            pnl = row["close"] - position["entry_price"]
            trades.append({
                "entry_time":  position["entry_time"],
                "exit_time":   row["datetime"],
                "entry_price": position["entry_price"],
                "exit_price":  row["close"],
                "pnl":         pnl,
                "forced":      False,
                "result":      "WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "DRAW"),
            })
            position = None

    # データ末尾にポジションが残っていれば強制クローズ
    if position is not None:
        last = df.iloc[-1]
        pnl = last["close"] - position["entry_price"]
        trades.append({
            "entry_time":  position["entry_time"],
            "exit_time":   last["datetime"],
            "entry_price": position["entry_price"],
            "exit_price":  last["close"],
            "pnl":         pnl,
            "forced":      True,
            "result":      "WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "DRAW"),
        })

    return trades


# ──────────────────────────────────────────────
# 統計計算
# ──────────────────────────────────────────────

def calc_stats(trades: list) -> dict:
    """勝率・損益などの統計指標を計算する。"""
    if not trades:
        return {}

    pnl_list     = [t["pnl"] for t in trades]
    wins         = sum(1 for t in trades if t["result"] == "WIN")
    losses       = sum(1 for t in trades if t["result"] == "LOSS")
    draws        = len(trades) - wins - losses
    gross_profit = sum(p for p in pnl_list if p > 0)
    gross_loss   = abs(sum(p for p in pnl_list if p < 0))

    return {
        "total_trades":  len(trades),
        "wins":          wins,
        "losses":        losses,
        "draws":         draws,
        "win_rate":      wins / len(trades) * 100,
        "total_pnl":     sum(pnl_list),
        "avg_pnl":       sum(pnl_list) / len(trades),
        "max_win":       max(pnl_list),
        "max_loss":      min(pnl_list),
        "gross_profit":  gross_profit,
        "gross_loss":    gross_loss,
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else float("inf"),
    }


# ──────────────────────────────────────────────
# 表示ヘルパー
# ──────────────────────────────────────────────

def _trade_rows(trades: list) -> list:
    """tabulate 用のトレード行リストを生成する（色なし・整列崩れ防止）。"""
    rows = []
    for i, t in enumerate(trades, 1):
        exit_label = f"{t['exit_time'].strftime('%m/%d %H:%M')}"
        if t["forced"]:
            exit_label += "*"   # 強制決済マーク
        rows.append([
            i,
            t["entry_time"].strftime("%m/%d %H:%M"),
            exit_label,
            f"{t['entry_price']:>10,.1f}",
            f"{t['exit_price']:>10,.1f}",
            f"{t['pnl']:>+10,.1f}",
            t["result"],
        ])
    return rows


TRADE_HEADERS = ["No", "エントリー", "エグジット", "始値(円)", "終値(円)", "損益(円)", "結果"]


def _period_str(df: pd.DataFrame) -> str:
    return (
        f"{df['datetime'].iloc[0].strftime('%Y-%m-%d')} 〜 "
        f"{df['datetime'].iloc[-1].strftime('%Y-%m-%d')}"
    )


# ──────────────────────────────────────────────
# ターミナル出力
# ──────────────────────────────────────────────

def print_summary(stats: dict, df: pd.DataFrame, trades: list) -> None:
    """統計サマリーと直近トレードをターミナルに表示する。"""
    SEP = "=" * 62

    print()
    print(SEP)
    print(f"  バックテスト結果  [ {TICKER} / {BACKTEST_INTERVAL} ]")
    print(SEP)
    print(f"  取得期間   : {_period_str(df)}")
    print(f"  総バー数   : {len(df):,} 本")
    print()

    if not stats:
        print("  トレードなし（シグナルが発生しませんでした）")
        print(SEP)
        return

    # 勝敗サマリー
    print(f"  総トレード数       : {stats['total_trades']:>4} 回")
    print(f"  勝ち               : {Fore.GREEN}{stats['wins']:>4} 回{Style.RESET_ALL}")
    print(f"  負け               : {Fore.RED}{stats['losses']:>4} 回{Style.RESET_ALL}")
    print(f"  引き分け           : {stats['draws']:>4} 回")
    print(f"  勝率               : {stats['win_rate']:>6.1f} %")
    print()

    # 損益サマリー
    pnl_color = Fore.GREEN if stats["total_pnl"] >= 0 else Fore.RED
    pf_val    = stats["profit_factor"]
    pf_str    = f"{pf_val:.2f}" if pf_val != float("inf") else "∞"
    pf_color  = Fore.GREEN if pf_val >= 1.0 else Fore.RED

    print(f"  合計損益           : {pnl_color}{stats['total_pnl']:>+10,.1f} 円{Style.RESET_ALL}")
    print(f"  平均損益 / トレード: {stats['avg_pnl']:>+10,.1f} 円")
    print(f"  最大利益           : {Fore.GREEN}{stats['max_win']:>+10,.1f} 円{Style.RESET_ALL}")
    print(f"  最大損失           : {Fore.RED}{stats['max_loss']:>+10,.1f} 円{Style.RESET_ALL}")
    print(f"  総利益             : {stats['gross_profit']:>10,.1f} 円")
    print(f"  総損失             : {stats['gross_loss']:>10,.1f} 円")
    print(f"  プロフィットファクター : {pf_color}{pf_str}{Style.RESET_ALL}")
    print()

    # 直近トレードテーブル（最大 10 件）
    recent = trades[-10:]
    print(f"  ── 直近 {len(recent)} トレード（* = データ末尾での強制決済）──")
    print(
        tabulate(
            _trade_rows(recent),
            headers=TRADE_HEADERS,
            tablefmt="simple",
            stralign="right",
            numalign="right",
        )
    )
    print()

    print(SEP)
    print("  ※ スリッページ・手数料は含まれていません")
    print("  ※ 本結果は将来の利益を保証しません")
    print("  ※ 自動発注機能はありません（分析のみ）")
    print(SEP)


# ──────────────────────────────────────────────
# レポートファイル出力
# ──────────────────────────────────────────────

def save_report(stats: dict, df: pd.DataFrame, trades: list, filepath: str) -> None:
    """全トレード一覧を含むバックテストレポートをテキストファイルに保存する。"""
    SEP = "=" * 62
    lines = []

    lines += [
        SEP,
        f"  バックテスト結果  [ {TICKER} / {BACKTEST_INTERVAL} ]",
        SEP,
        f"  取得期間   : {_period_str(df)}",
        f"  総バー数   : {len(df):,} 本",
        "",
    ]

    if not stats:
        lines.append("  トレードなし（シグナルが発生しませんでした）")
    else:
        pf_val = stats["profit_factor"]
        pf_str = f"{pf_val:.2f}" if pf_val != float("inf") else "inf"

        lines += [
            f"  総トレード数       : {stats['total_trades']:>4} 回",
            f"  勝ち               : {stats['wins']:>4} 回",
            f"  負け               : {stats['losses']:>4} 回",
            f"  引き分け           : {stats['draws']:>4} 回",
            f"  勝率               : {stats['win_rate']:>6.1f} %",
            "",
            f"  合計損益           : {stats['total_pnl']:>+10,.1f} 円",
            f"  平均損益 / トレード: {stats['avg_pnl']:>+10,.1f} 円",
            f"  最大利益           : {stats['max_win']:>+10,.1f} 円",
            f"  最大損失           : {stats['max_loss']:>+10,.1f} 円",
            f"  総利益             : {stats['gross_profit']:>10,.1f} 円",
            f"  総損失             : {stats['gross_loss']:>10,.1f} 円",
            f"  プロフィットファクター : {pf_str}",
            "",
            "  ── 全トレード一覧（* = データ末尾での強制決済）──",
            tabulate(
                _trade_rows(trades),
                headers=TRADE_HEADERS,
                tablefmt="simple",
                stralign="right",
                numalign="right",
            ),
            "",
        ]

    lines += [
        SEP,
        "  注意事項",
        "  - スリッページ・手数料は含まれていません",
        "  - 本結果は将来の利益を保証しません",
        "  - 自動発注機能はありません（分析のみ）",
        SEP,
    ]

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"レポートを保存しました → {filepath}")


# ──────────────────────────────────────────────
# メイン処理
# ──────────────────────────────────────────────

def main() -> None:
    print("バックテスト用データを取得中...")
    df_raw = fetch_ohlcv(
        period=BACKTEST_PERIOD,
        interval=BACKTEST_INTERVAL,
        limit=0,   # 全件取得（件数制限なし）
    )

    print("インジケーターとシグナルを計算中（日次 VWAP / CVD リセット）...")
    df = prepare_data(df_raw)

    print("トレードをシミュレーション中...")
    trades = simulate_trades(df)

    stats = calc_stats(trades)

    print_summary(stats, df, trades)
    save_report(stats, df, trades, filepath=REPORT_FILE)


if __name__ == "__main__":
    main()
