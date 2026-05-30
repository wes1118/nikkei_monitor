"""
strategy.py - 売買シグナルの判定ロジック
"""

import pandas as pd


# ──────────────────────────────────────────────
# v1.6 設定（変更したい場合はここだけ編集する）
# ──────────────────────────────────────────────

VOLUME_MULTIPLIER = 1.5   # 出来高が移動平均の何倍以上あればシグナル有効
ATR_MIN           = 30    # 円: ATR がこの値より小さい場合は取引しない（レンジ相場除外）
EMA_WINDOW        = 20    # EMA の期間（indicators.py の calculate_ema と合わせる）


# ──────────────────────────────────────────────
# v1.6 シグナル（現行版）
# ──────────────────────────────────────────────

def _judge_row_v16(row: pd.Series) -> str:
    """v1.6 判定ロジック — 5 条件すべてを満たした場合のみシグナルを出す。

    BUY 条件（5つ全て必要）:
        1. 終値 > VWAP          — 日中の価格帯が買い優勢
        2. CVD > 0              — 累積で買い圧力が強い
        3. 出来高 > 移動平均×1.5 — 平均の1.5倍以上の強い出来高（v1.5の単純比較より厳しい）
        4. 終値 > EMA           — 短期上昇トレンド中
        5. ATR >= ATR_MIN       — 十分なボラティリティがある（レンジ相場を除外）

    SELL 条件（5つ全て必要）:
        1. 終値 < VWAP
        2. CVD < 0
        3. 出来高 > 移動平均×1.5
        4. 終値 < EMA           — 短期下降トレンド中
        5. ATR >= ATR_MIN

    それ以外: 見送り
    """
    above_vwap      = row["close"] > row["vwap"]
    below_vwap      = row["close"] < row["vwap"]
    cvd_positive    = row["cvd"] > 0
    cvd_negative    = row["cvd"] < 0
    strong_volume   = row["volume"] > row["vol_avg"] * VOLUME_MULTIPLIER
    uptrend         = row["close"] > row["ema"]
    downtrend       = row["close"] < row["ema"]
    enough_volatile = row["atr"] >= ATR_MIN

    if above_vwap and cvd_positive and strong_volume and uptrend and enough_volatile:
        return "買い"
    elif below_vwap and cvd_negative and strong_volume and downtrend and enough_volatile:
        return "売り"
    else:
        return "見送り"


def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    """v1.6: VWAP + CVD + 出来高1.5倍 + EMA トレンドフィルター + ATR ボラティリティフィルター。

    ※ 事前に calculate_ema() と calculate_atr() を呼んでおく必要がある。
    """
    df["signal"] = df.apply(_judge_row_v16, axis=1)
    return df


# ──────────────────────────────────────────────
# v1.5 シグナル（比較用・変更しない）
# ──────────────────────────────────────────────

def _judge_row_v15(row: pd.Series) -> str:
    """v1.5 判定ロジック — 3 条件。比較目的で保持する。

    BUY 条件:
        終値 > VWAP  AND  CVD > 0  AND  出来高 > 移動平均
    SELL 条件:
        終値 < VWAP  AND  CVD < 0  AND  出来高 > 移動平均
    """
    above_vwap   = row["close"] > row["vwap"]
    below_vwap   = row["close"] < row["vwap"]
    cvd_positive = row["cvd"] > 0
    cvd_negative = row["cvd"] < 0
    high_volume  = row["volume"] > row["vol_avg"]

    if above_vwap and cvd_positive and high_volume:
        return "買い"
    elif below_vwap and cvd_negative and high_volume:
        return "売り"
    else:
        return "見送り"


def generate_signals_v15(df: pd.DataFrame) -> pd.DataFrame:
    """v1.5: VWAP + CVD + 出来高（比較用）。EMA/ATR 列は不要。"""
    df["signal"] = df.apply(_judge_row_v15, axis=1)
    return df
