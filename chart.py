"""
chart.py - チャート生成モジュール
価格・VWAP・CVD・シグナルマーカーを chart.png に保存する。
"""

import matplotlib
matplotlib.use("Agg")  # 画面表示なし（ファイル保存のみ）

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd


def save_chart(df: pd.DataFrame, filepath: str = "chart.png") -> None:
    """チャートを生成して PNG ファイルに保存する。

    上段: 価格ライン + VWAP ライン + BUY/SELL マーカー
    下段: CVD バーチャート
    """
    fig, (ax_price, ax_cvd) = plt.subplots(
        nrows=2,
        ncols=1,
        figsize=(12, 7),
        gridspec_kw={"height_ratios": [3, 1]},
        sharex=True,
    )
    fig.patch.set_facecolor("#1a1a2e")

    x = df["datetime"]

    # ── 上段: 価格 & VWAP ──────────────────────────────────
    ax_price.set_facecolor("#16213e")

    ax_price.plot(x, df["close"], color="#00d4ff", linewidth=1.5, label="Close")
    ax_price.plot(x, df["vwap"],  color="#ffa500", linewidth=1.5, linestyle="--", label="VWAP")

    # BUY markers (▲ green)
    buy_mask = df["signal"] == "買い"
    if buy_mask.any():
        ax_price.scatter(
            x[buy_mask],
            df["close"][buy_mask],
            marker="^",
            color="#00ff88",
            s=120,
            zorder=5,
            label="BUY",
        )

    # SELL markers (▼ red)
    sell_mask = df["signal"] == "売り"
    if sell_mask.any():
        ax_price.scatter(
            x[sell_mask],
            df["close"][sell_mask],
            marker="v",
            color="#ff4466",
            s=120,
            zorder=5,
            label="SELL",
        )

    ax_price.set_ylabel("Price (JPY)", color="#cccccc")
    ax_price.tick_params(colors="#cccccc")
    ax_price.yaxis.label.set_color("#cccccc")
    ax_price.spines["bottom"].set_color("#444466")
    ax_price.spines["top"].set_color("#444466")
    ax_price.spines["left"].set_color("#444466")
    ax_price.spines["right"].set_color("#444466")
    ax_price.grid(True, linestyle="--", alpha=0.3, color="#444466")
    ax_price.legend(
        loc="upper left",
        facecolor="#16213e",
        edgecolor="#444466",
        labelcolor="#cccccc",
        fontsize=9,
    )
    ax_price.set_title(
        "Nikkei 225 mini  [ Price / VWAP / Signals ]",
        color="#ffffff",
        fontsize=12,
        pad=10,
    )

    # ── 下段: CVD ─────────────────────────────────────────
    ax_cvd.set_facecolor("#16213e")

    colors = ["#00ff88" if v >= 0 else "#ff4466" for v in df["cvd"]]
    ax_cvd.bar(x, df["cvd"], color=colors, width=pd.Timedelta(minutes=3), align="center")
    ax_cvd.axhline(0, color="#888899", linewidth=0.8, linestyle="-")

    ax_cvd.set_ylabel("CVD", color="#cccccc")
    ax_cvd.set_xlabel("Time", color="#cccccc")
    ax_cvd.tick_params(colors="#cccccc")
    ax_cvd.yaxis.label.set_color("#cccccc")
    ax_cvd.xaxis.label.set_color("#cccccc")
    ax_cvd.spines["bottom"].set_color("#444466")
    ax_cvd.spines["top"].set_color("#444466")
    ax_cvd.spines["left"].set_color("#444466")
    ax_cvd.spines["right"].set_color("#444466")
    ax_cvd.grid(True, linestyle="--", alpha=0.3, color="#444466")

    # X 軸: 時刻フォーマット
    ax_cvd.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax_cvd.xaxis.set_major_locator(mdates.MinuteLocator(byminute=range(0, 60, 15)))
    plt.setp(ax_cvd.xaxis.get_majorticklabels(), rotation=45, ha="right", color="#cccccc")

    plt.tight_layout(pad=2.0)
    plt.savefig(filepath, dpi=150, facecolor=fig.get_facecolor())
    plt.close(fig)

    print(f"チャートを保存しました → {filepath}")
