"""
chart.py - チャート生成モジュール
価格・VWAP・CVD・シグナルマーカーを chart.png に保存する。
日本語フォントが利用できる場合は日本語ラベルを使用し、
見つからない場合は英語ラベルにフォールバックする。
"""

import os
import matplotlib
matplotlib.use("Agg")  # 画面表示なし（ファイル保存のみ）

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib import font_manager
import pandas as pd


# ──────────────────────────────────────────────
# 日本語フォント検出・登録
# ──────────────────────────────────────────────

def _find_and_register_japanese_font() -> str | None:
    """Windows のフォントフォルダから日本語フォントを探し、
    matplotlib に登録してフォント名を返す。見つからない場合は None。

    試みる順序:
        1. Yu Gothic  (Windows 10/11 標準)
        2. Meiryo     (Windows Vista 以降)
        3. MS Gothic  (旧 Windows でも利用可能)
        4. MS Mincho  (旧 Windows でも利用可能)
    """
    font_dir = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts")
    candidates = [
        ("Yu Gothic", "YuGothR.ttc"),
        ("Meiryo",    "meiryo.ttc"),
        ("MS Gothic", "msgothic.ttc"),
        ("MS Mincho", "msmincho.ttc"),
    ]
    for name, filename in candidates:
        path = os.path.join(font_dir, filename)
        if os.path.exists(path):
            try:
                font_manager.fontManager.addfont(path)  # matplotlib 3.5+
            except AttributeError:
                pass  # 古い matplotlib でも name を返して rcParams に任せる
            return name
    return None


_JP_FONT = _find_and_register_japanese_font()

if _JP_FONT:
    plt.rcParams["font.family"]        = _JP_FONT
    plt.rcParams["axes.unicode_minus"] = False  # 日本語フォントでのマイナス記号崩れを防止


# ──────────────────────────────────────────────
# ラベル（日本語 / 英語フォールバック）
# ──────────────────────────────────────────────

if _JP_FONT:
    _L = {
        "title":   "日経225mini  [ 価格 / VWAP / シグナル ]",
        "close":   "終値",
        "vwap":    "VWAP",
        "buy":     "買い ▲",
        "sell":    "売り ▼",
        "y_price": "価格（円）",
        "y_cvd":   "累積出来高デルタ（CVD）",
        "x_time":  "時刻",
    }
else:
    _L = {
        "title":   "Nikkei 225 mini  [ Price / VWAP / Signals ]",
        "close":   "Close",
        "vwap":    "VWAP",
        "buy":     "BUY ▲",
        "sell":    "SELL ▼",
        "y_price": "Price (JPY)",
        "y_cvd":   "CVD",
        "x_time":  "Time",
    }


# ──────────────────────────────────────────────
# チャート生成
# ──────────────────────────────────────────────

def save_chart(df: pd.DataFrame, filepath: str = "chart.png") -> None:
    """チャートを生成して PNG ファイルに保存する。

    上段: 価格ライン + VWAP + BUY/SELL マーカー
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

    ax_price.plot(x, df["close"], color="#00d4ff", linewidth=1.5, label=_L["close"])
    ax_price.plot(x, df["vwap"],  color="#ffa500", linewidth=1.5, linestyle="--", label=_L["vwap"])

    # 買いシグナルマーカー（▲ 緑）
    buy_mask = df["signal"] == "買い"
    if buy_mask.any():
        ax_price.scatter(
            x[buy_mask],
            df["close"][buy_mask],
            marker="^",
            color="#00ff88",
            s=120,
            zorder=5,
            label=_L["buy"],
        )

    # 売りシグナルマーカー（▼ 赤）
    sell_mask = df["signal"] == "売り"
    if sell_mask.any():
        ax_price.scatter(
            x[sell_mask],
            df["close"][sell_mask],
            marker="v",
            color="#ff4466",
            s=120,
            zorder=5,
            label=_L["sell"],
        )

    ax_price.set_ylabel(_L["y_price"], color="#cccccc")
    ax_price.tick_params(colors="#cccccc")
    ax_price.yaxis.label.set_color("#cccccc")
    for spine in ax_price.spines.values():
        spine.set_color("#444466")
    ax_price.grid(True, linestyle="--", alpha=0.3, color="#444466")
    ax_price.legend(
        loc="upper left",
        facecolor="#16213e",
        edgecolor="#444466",
        labelcolor="#cccccc",
        fontsize=9,
    )
    ax_price.set_title(_L["title"], color="#ffffff", fontsize=12, pad=10)

    # ── 下段: CVD ─────────────────────────────────────────
    ax_cvd.set_facecolor("#16213e")

    colors = ["#00ff88" if v >= 0 else "#ff4466" for v in df["cvd"]]
    ax_cvd.bar(x, df["cvd"], color=colors, width=pd.Timedelta(minutes=3), align="center")
    ax_cvd.axhline(0, color="#888899", linewidth=0.8)

    ax_cvd.set_ylabel(_L["y_cvd"], color="#cccccc")
    ax_cvd.set_xlabel(_L["x_time"], color="#cccccc")
    ax_cvd.tick_params(colors="#cccccc")
    ax_cvd.yaxis.label.set_color("#cccccc")
    ax_cvd.xaxis.label.set_color("#cccccc")
    for spine in ax_cvd.spines.values():
        spine.set_color("#444466")
    ax_cvd.grid(True, linestyle="--", alpha=0.3, color="#444466")

    ax_cvd.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax_cvd.xaxis.set_major_locator(mdates.MinuteLocator(byminute=range(0, 60, 15)))
    plt.setp(ax_cvd.xaxis.get_majorticklabels(), rotation=45, ha="right", color="#cccccc")

    plt.tight_layout(pad=2.0)
    plt.savefig(filepath, dpi=150, facecolor=fig.get_facecolor())
    plt.close(fig)

    font_info = f"（フォント: {_JP_FONT}）" if _JP_FONT else "（日本語フォントなし → 英語ラベル）"
    print(f"チャートを保存しました → {filepath}  {font_info}")
