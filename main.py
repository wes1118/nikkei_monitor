"""
main.py - 日経225mini 監視システム
自動発注機能なし。表示のみ。
"""

import sys

# Windows PowerShell で日本語を正しく表示するために UTF-8 に切り替える
sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd
from tabulate import tabulate
import colorama
from colorama import Fore, Style

from data_source import fetch_ohlcv
from indicators import calculate_vwap, calculate_volume_avg, calculate_cvd
from strategy import generate_signals
from chart import save_chart
from notifier import notify

# Windows ターミナルで色を使えるように初期化
colorama.init()


# ──────────────────────────────────────────────
# 表示ヘルパー
# ──────────────────────────────────────────────

def _color_signal(signal: str) -> str:
    """シグナルに色を付ける。"""
    if signal == "買い":
        return Fore.GREEN + signal + Style.RESET_ALL
    elif signal == "売り":
        return Fore.RED + signal + Style.RESET_ALL
    else:
        return Fore.YELLOW + signal + Style.RESET_ALL


def display_results(df: pd.DataFrame) -> None:
    """計算結果をターミナルに表示する。"""
    date_range = (
        f"{df['datetime'].iloc[0].strftime('%Y-%m-%d %H:%M')}"
        f" 〜 {df['datetime'].iloc[-1].strftime('%H:%M')} JST"
    )
    print("\n" + "=" * 72)
    print("  日経225mini 監視システム  【Yahoo Finance データ / 発注機能なし】")
    print(f"  期間: {date_range}")
    print("=" * 72)

    # 表示用にコピーして整形
    disp = df.copy()
    disp["時刻"] = disp["datetime"].dt.strftime("%H:%M")
    disp["VWAP"] = disp["vwap"].round(1)
    disp["出来高MA"] = disp["vol_avg"].round(0).astype(int)
    disp["CVD"] = disp["cvd"].astype(int)
    disp["シグナル"] = disp["signal"].apply(_color_signal)

    table_data = disp[
        ["時刻", "open", "high", "low", "close", "volume", "VWAP", "出来高MA", "CVD", "シグナル"]
    ].values.tolist()

    headers = ["時刻", "始値", "高値", "安値", "終値", "出来高", "VWAP", "出来高MA", "CVD", "シグナル"]

    print(
        tabulate(
            table_data,
            headers=headers,
            tablefmt="simple",
            numalign="right",
            stralign="right",
        )
    )

    # 最新バーのサマリー
    latest = df.iloc[-1]
    print("\n" + "-" * 72)
    print(f"  【最新シグナル】 {_color_signal(latest['signal'])}")
    print(
        f"  終値: {latest['close']:,.1f} 円  "
        f"VWAP: {latest['vwap']:,.1f}  "
        f"CVD: {latest['cvd']:+,}  "
        f"出来高: {latest['volume']:,} / 平均: {latest['vol_avg']:,.0f}"
    )
    print("=" * 72 + "\n")

    # シグナル集計
    counts = df["signal"].value_counts()
    print("  シグナル集計:")
    for label, color in [("買い", Fore.GREEN), ("売り", Fore.RED), ("見送り", Fore.YELLOW)]:
        count = counts.get(label, 0)
        bar = "#" * count
        print(f"    {color}{label}{Style.RESET_ALL}: {bar} ({count}本)")
    print()


# ──────────────────────────────────────────────
# メイン処理
# ──────────────────────────────────────────────

def main() -> None:
    print("市場データを取得中...")
    df = fetch_ohlcv()

    print("インジケーターを計算中...")
    df = calculate_vwap(df)
    df = calculate_volume_avg(df, window=5)   # 5本移動平均
    df = calculate_cvd(df)

    print("シグナルを判定中...")
    df = generate_signals(df)

    display_results(df)

    print("チャートを生成中...")
    save_chart(df, filepath="chart.png")

    latest = df.iloc[-1]
    notify(
        signal=latest["signal"],
        close=latest["close"],
        cvd=int(latest["cvd"]),
    )


if __name__ == "__main__":
    main()
