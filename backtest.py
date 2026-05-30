"""
backtest.py - シンプルバックテスト v1.5
過去データに BUY/SELL シグナルを適用して損益をシミュレーションする。
自動発注機能なし。分析のみ。
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd
from tabulate import tabulate
import colorama
from colorama import Fore, Style

from data_source import fetch_ohlcv, TICKER          # TICKER は data_source.py で一元管理
from session_filter import filter_session, session_label, session_desc, SESSION  # SESSION は session_filter.py で一元管理
from indicators import calculate_vwap, calculate_volume_avg, calculate_cvd, calculate_ema, calculate_atr
from strategy import generate_signals

colorama.init()

# ──────────────────────────────────────────────
# 設定
# ──────────────────────────────────────────────

# TICKER  は data_source.py    で設定（ここでは再定義しない）
# SESSION は session_filter.py で設定（ここでは再定義しない）
BACKTEST_PERIOD   = "60d"    # yfinance の 5 分足は最大 60 日まで無料取得可能
BACKTEST_INTERVAL = "5m"
VOL_WINDOW        = 5
REPORT_FILE       = "backtest_report.txt"

STOP_LOSS        = 150   # 円: エントリー価格からの損切り幅
TAKE_PROFIT      = 300   # 円: エントリー価格からの利確幅
SLIPPAGE         = 10    # 円: 1 回あたりのスリッページ（エントリー・エグジット各 1 回）
TRANSACTION_COST = 20    # 円: 1 トレード（往復）あたりの取引コスト
TOTAL_COST       = 2 * SLIPPAGE + TRANSACTION_COST  # = 40 円 / トレード


# ──────────────────────────────────────────────
# データ準備
# ──────────────────────────────────────────────

def prepare_data(df: pd.DataFrame, signal_fn=None, session: str = SESSION) -> pd.DataFrame:
    """セッションフィルターを適用してから全指標を計算し、シグナルを付与する。

    引数:
        signal_fn - シグナル生成関数（デフォルト: generate_signals = v1.6）
        session   - セッションフィルター（"all_sessions" / "day_session" / "night_session"）
                    デフォルトは session_filter.py の SESSION 定数

    日次リセットするもの: VWAP、CVD、EMA（セッション内の累積値・トレンド）
    通しで計算するもの  : 出来高移動平均、ATR（複数日にわたる統計が意味を持つ）
    """
    if signal_fn is None:
        signal_fn = generate_signals

    # セッションフィルターを最初に適用する
    df = filter_session(df, session)
    if df.empty:
        raise ValueError(
            f"セッションフィルター後にデータがありません: {session}\n"
            "  ヒント: ^N225 は日本市場時間のみです。night_session には NIY=F を推奨します。"
        )

    df = df.copy()
    df["_date"] = df["datetime"].dt.date

    day_groups = []
    for _, day_df in df.groupby("_date", sort=True):
        day_df = day_df.copy().reset_index(drop=True)
        day_df = calculate_vwap(day_df)
        day_df = calculate_cvd(day_df)
        day_df = calculate_ema(day_df, window=20)   # セッションごとにリセット
        day_groups.append(day_df)

    result = pd.concat(day_groups).reset_index(drop=True)
    result = calculate_volume_avg(result, window=VOL_WINDOW)
    result = calculate_atr(result, period=14)        # 日をまたいで計算
    result = signal_fn(result)
    return result.drop(columns=["_date"])


# ──────────────────────────────────────────────
# トレードシミュレーション
# ──────────────────────────────────────────────

def _record(trades: list, pos: dict, exit_price: float,
            reason: str, exit_bar: int, exit_time) -> None:
    """計算済みの決済情報をトレードリストに追記する。"""
    pnl = (exit_price - pos["entry_price"]) - TOTAL_COST
    trades.append({
        "entry_time":   pos["entry_time"],
        "exit_time":    exit_time,
        "entry_price":  pos["entry_price"],
        "exit_price":   exit_price,
        "pnl":          pnl,
        "exit_reason":  reason,
        "holding_bars": exit_bar - pos["entry_bar"],
        "result":       "WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "DRAW"),
    })


def simulate_trades(df: pd.DataFrame) -> list:
    """BUY シグナルでロングエントリーし、以下の優先順で決済するシミュレーション。

    決済優先順位（同バー内で複数条件が重なった場合）:
      1. ストップロス (SL): bar の安値が (エントリー価格 - SL幅) を下回った
      2. テイクプロフィット (TP): bar の高値が (エントリー価格 + TP幅) を上回った
      3. シグナル決済: SELL シグナルが出た
    期末に未決済のポジションは最終バーの終値で強制決済する。

    損益の計算式:
        P&L = (出口価格 - 入口価格) - SLIPPAGE×2 - TRANSACTION_COST
            = (出口価格 - 入口価格) - 40 円

    ※ SL を優先することで、SL と TP が同時に触れた最悪ケースを想定している（保守的）。
    """
    trades   = []
    position = None  # None = フラット

    for idx, row in df.iterrows():
        # ── エントリー ──────────────────────────
        if position is None and row["signal"] == "買い":
            position = {
                "entry_time":  row["datetime"],
                "entry_bar":   idx,
                "entry_price": row["close"],
                "sl_level":    row["close"] - STOP_LOSS,
                "tp_level":    row["close"] + TAKE_PROFIT,
            }

        # ── 決済チェック（エントリーバーは除く）──
        elif position is not None:
            if row["low"] <= position["sl_level"]:
                _record(trades, position, position["sl_level"], "SL", idx, row["datetime"])
                position = None
            elif row["high"] >= position["tp_level"]:
                _record(trades, position, position["tp_level"], "TP", idx, row["datetime"])
                position = None
            elif row["signal"] == "売り":
                _record(trades, position, row["close"], "SIGNAL", idx, row["datetime"])
                position = None

    # 期末強制決済
    if position is not None:
        last = df.iloc[-1]
        _record(trades, position, last["close"], "FORCED", df.index[-1], last["datetime"])

    return trades


# ──────────────────────────────────────────────
# 統計計算
# ──────────────────────────────────────────────

def calc_stats(trades: list) -> dict:
    """勝率・損益・ドローダウン・連勝連敗などを計算する。"""
    if not trades:
        return {}

    pnl_list = [t["pnl"] for t in trades]
    results  = [t["result"] for t in trades]
    wins     = results.count("WIN")
    losses   = results.count("LOSS")
    draws    = results.count("DRAW")

    gross_profit = sum(p for p in pnl_list if p > 0)
    gross_loss   = abs(sum(p for p in pnl_list if p < 0))

    # 最大ドローダウン（累積損益の峰から谷への最大落差）
    cumulative = 0
    peak       = 0
    max_dd     = 0
    for p in pnl_list:
        cumulative += p
        if cumulative > peak:
            peak = cumulative
        dd = cumulative - peak
        if dd < max_dd:
            max_dd = dd

    # 連勝・連敗
    max_win_streak  = cur_win  = 0
    max_loss_streak = cur_loss = 0
    for r in results:
        if r == "WIN":
            cur_win  += 1;  cur_loss  = 0
            max_win_streak  = max(max_win_streak,  cur_win)
        elif r == "LOSS":
            cur_loss += 1;  cur_win   = 0
            max_loss_streak = max(max_loss_streak, cur_loss)
        else:
            cur_win = cur_loss = 0

    return {
        "total_trades":    len(trades),
        "wins":            wins,
        "losses":          losses,
        "draws":           draws,
        "win_rate":        wins / len(trades) * 100,
        "total_pnl":       sum(pnl_list),
        "avg_pnl":         sum(pnl_list) / len(trades),
        "max_win":         max(pnl_list),
        "max_loss":        min(pnl_list),
        "gross_profit":    gross_profit,
        "gross_loss":      gross_loss,
        "profit_factor":   gross_profit / gross_loss if gross_loss > 0 else float("inf"),
        "max_drawdown":    max_dd,
        "avg_hold_bars":   sum(t["holding_bars"] for t in trades) / len(trades),
        "max_win_streak":  max_win_streak,
        "max_loss_streak": max_loss_streak,
        "sl_count":        sum(1 for t in trades if t["exit_reason"] == "SL"),
        "tp_count":        sum(1 for t in trades if t["exit_reason"] == "TP"),
        "signal_count":    sum(1 for t in trades if t["exit_reason"] == "SIGNAL"),
        "forced_count":    sum(1 for t in trades if t["exit_reason"] == "FORCED"),
    }


# ──────────────────────────────────────────────
# 表示ヘルパー
# ──────────────────────────────────────────────

_EXIT_LABEL = {"SL": "SL", "TP": "TP", "SIGNAL": "シグナル", "FORCED": "強制*"}

TRADE_HEADERS = [
    "No", "エントリー", "エグジット",
    "始値(円)", "終値(円)", "損益(円)", "保有本", "決済", "結果",
]


def _trade_rows(trades: list) -> list:
    """tabulate 用の行リストを生成する（ANSI なし・整列崩れ防止）。"""
    rows = []
    for i, t in enumerate(trades, 1):
        rows.append([
            i,
            t["entry_time"].strftime("%m/%d %H:%M"),
            t["exit_time"].strftime("%m/%d %H:%M"),
            f"{t['entry_price']:>10,.1f}",
            f"{t['exit_price']:>10,.1f}",
            f"{t['pnl']:>+10,.1f}",
            t["holding_bars"],
            _EXIT_LABEL.get(t["exit_reason"], t["exit_reason"]),
            t["result"],
        ])
    return rows


def _period_str(df: pd.DataFrame) -> str:
    return (
        f"{df['datetime'].iloc[0].strftime('%Y-%m-%d')} 〜 "
        f"{df['datetime'].iloc[-1].strftime('%Y-%m-%d')}"
    )


def _pf_str(pf: float) -> str:
    return f"{pf:.2f}" if pf != float("inf") else "∞"


# ──────────────────────────────────────────────
# ターミナル出力
# ──────────────────────────────────────────────

def print_summary(stats: dict, df: pd.DataFrame, trades: list,
                  session: str = SESSION) -> None:
    """統計サマリーと直近トレードをターミナルに表示する。"""
    SEP = "=" * 64

    print()
    print(SEP)
    print(f"  バックテスト結果 v1.6  [ {TICKER} / {BACKTEST_INTERVAL} ]")
    print(SEP)
    print(f"  取得期間   : {_period_str(df)}")
    print(f"  総バー数   : {len(df):,} 本")
    print(f"  セッション : {session_label(session)}  ({session_desc(session)})")
    print()

    # シミュレーション設定
    print("  ── シミュレーション設定 ──")
    print(f"  ストップロス          : {STOP_LOSS:>5} 円 (エントリー価格 −{STOP_LOSS}円で損切り)")
    print(f"  テイクプロフィット    : {TAKE_PROFIT:>5} 円 (エントリー価格 +{TAKE_PROFIT}円で利確)")
    print(f"  スリッページ          : {SLIPPAGE:>5} 円 / 片道（エントリー・エグジット各1回）")
    print(f"  取引コスト            : {TRANSACTION_COST:>5} 円 / トレード")
    print(f"  合計コスト（往復）    : {TOTAL_COST:>5} 円 / トレード")
    print()

    if not stats:
        print("  トレードなし（シグナルが発生しませんでした）")
        print(SEP)
        return

    # 勝敗
    print("  ── 勝敗 ──")
    print(f"  総トレード数       : {stats['total_trades']:>4} 回")
    print(f"  勝ち               : {Fore.GREEN}{stats['wins']:>4} 回{Style.RESET_ALL}")
    print(f"  負け               : {Fore.RED}{stats['losses']:>4} 回{Style.RESET_ALL}")
    print(f"  引き分け           : {stats['draws']:>4} 回")
    print(f"  勝率               : {stats['win_rate']:>6.1f} %")
    print(f"  最大連勝           : {stats['max_win_streak']:>4} 連勝")
    print(f"  最大連敗           : {stats['max_loss_streak']:>4} 連敗")
    print()

    # 損益
    pnl_color = Fore.GREEN if stats["total_pnl"] >= 0 else Fore.RED
    pf        = stats["profit_factor"]
    pf_color  = Fore.GREEN if pf >= 1.0 else Fore.RED

    print("  ── 損益 ──")
    print(f"  合計損益           : {pnl_color}{stats['total_pnl']:>+10,.1f} 円{Style.RESET_ALL}")
    print(f"  平均損益/トレード  : {stats['avg_pnl']:>+10,.1f} 円")
    print(f"  最大利益           : {Fore.GREEN}{stats['max_win']:>+10,.1f} 円{Style.RESET_ALL}")
    print(f"  最大損失           : {Fore.RED}{stats['max_loss']:>+10,.1f} 円{Style.RESET_ALL}")
    print(f"  総利益             : {stats['gross_profit']:>10,.1f} 円")
    print(f"  総損失             : {stats['gross_loss']:>10,.1f} 円")
    print(f"  プロフィットファクター : {pf_color}{_pf_str(pf)}{Style.RESET_ALL}")
    print(f"  最大ドローダウン   : {Fore.RED}{stats['max_drawdown']:>+10,.1f} 円{Style.RESET_ALL}")
    print()

    # 保有・決済内訳
    avg_bars = stats["avg_hold_bars"]
    print("  ── 保有・決済内訳 ──")
    print(f"  平均保有本数       : {avg_bars:>6.1f} 本（≈ {avg_bars * 5:.0f} 分）")
    print(f"  ストップロス決済   : {stats['sl_count']:>4} 回")
    print(f"  テイクプロフィット決済 : {stats['tp_count']:>4} 回")
    print(f"  シグナル決済       : {stats['signal_count']:>4} 回")
    print(f"  強制決済（期末）   : {stats['forced_count']:>4} 回")
    print()

    # 直近 10 トレード
    recent = trades[-10:]
    print(f"  ── 直近 {len(recent)} トレード（* = 期末強制決済）──")
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
    print("  ※ 本結果は将来の利益を保証しません")
    print("  ※ 自動発注機能はありません（分析のみ）")
    print(SEP)


# ──────────────────────────────────────────────
# レポートファイル出力
# ──────────────────────────────────────────────

def save_report(stats: dict, df: pd.DataFrame, trades: list, filepath: str,
                session: str = SESSION) -> None:
    """全トレード一覧を含む詳細レポートをテキストファイルに保存する。"""
    SEP   = "=" * 64
    lines = []

    lines += [
        SEP,
        f"  バックテスト結果 v1.6  [ {TICKER} / {BACKTEST_INTERVAL} ]",
        SEP,
        f"  取得期間   : {_period_str(df)}",
        f"  総バー数   : {len(df):,} 本",
        f"  セッション : {session_label(session)}  ({session_desc(session)})",
        "",
        "  ── シミュレーション設定 ──",
        f"  ストップロス          : {STOP_LOSS:>5} 円",
        f"  テイクプロフィット    : {TAKE_PROFIT:>5} 円",
        f"  スリッページ          : {SLIPPAGE:>5} 円/片道",
        f"  取引コスト            : {TRANSACTION_COST:>5} 円/トレード",
        f"  合計コスト（往復）    : {TOTAL_COST:>5} 円/トレード",
        "",
    ]

    if not stats:
        lines.append("  トレードなし（シグナルが発生しませんでした）")
    else:
        pf       = stats["profit_factor"]
        avg_bars = stats["avg_hold_bars"]

        lines += [
            "  ── 勝敗 ──",
            f"  総トレード数       : {stats['total_trades']:>4} 回",
            f"  勝ち               : {stats['wins']:>4} 回",
            f"  負け               : {stats['losses']:>4} 回",
            f"  引き分け           : {stats['draws']:>4} 回",
            f"  勝率               : {stats['win_rate']:>6.1f} %",
            f"  最大連勝           : {stats['max_win_streak']:>4} 連勝",
            f"  最大連敗           : {stats['max_loss_streak']:>4} 連敗",
            "",
            "  ── 損益 ──",
            f"  合計損益           : {stats['total_pnl']:>+10,.1f} 円",
            f"  平均損益/トレード  : {stats['avg_pnl']:>+10,.1f} 円",
            f"  最大利益           : {stats['max_win']:>+10,.1f} 円",
            f"  最大損失           : {stats['max_loss']:>+10,.1f} 円",
            f"  総利益             : {stats['gross_profit']:>10,.1f} 円",
            f"  総損失             : {stats['gross_loss']:>10,.1f} 円",
            f"  プロフィットファクター : {_pf_str(pf)}",
            f"  最大ドローダウン   : {stats['max_drawdown']:>+10,.1f} 円",
            "",
            "  ── 保有・決済内訳 ──",
            f"  平均保有本数       : {avg_bars:>6.1f} 本（≈ {avg_bars * 5:.0f} 分）",
            f"  ストップロス決済   : {stats['sl_count']:>4} 回",
            f"  テイクプロフィット決済 : {stats['tp_count']:>4} 回",
            f"  シグナル決済       : {stats['signal_count']:>4} 回",
            f"  強制決済（期末）   : {stats['forced_count']:>4} 回",
            "",
            "  ── 全トレード一覧（* = 期末強制決済）──",
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
        "  - 本結果は将来の利益を保証しません",
        "  - 自動発注機能はありません（分析のみ）",
        SEP,
    ]

    with open(filepath, "w", encoding="utf-8-sig") as f:  # BOM付きでWindows Notepadでも文字化けしない
        f.write("\n".join(lines))

    print(f"レポートを保存しました → {filepath}")


# ──────────────────────────────────────────────
# メイン処理
# ──────────────────────────────────────────────

def main() -> None:
    print("バックテスト用データを取得中...")
    df_raw = fetch_ohlcv(
        ticker=TICKER,
        period=BACKTEST_PERIOD,
        interval=BACKTEST_INTERVAL,
        limit=0,
    )

    print(f"セッションフィルター: {session_label(SESSION)}  ({session_desc(SESSION)})")
    print("インジケーターとシグナルを計算中（日次 VWAP / CVD リセット）...")
    df = prepare_data(df_raw, session=SESSION)

    print("トレードをシミュレーション中...")
    trades = simulate_trades(df)

    stats = calc_stats(trades)
    print_summary(stats, df, trades, session=SESSION)
    save_report(stats, df, trades, filepath=REPORT_FILE, session=SESSION)


if __name__ == "__main__":
    main()
