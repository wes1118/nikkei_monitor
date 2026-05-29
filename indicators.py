"""
indicators.py - テクニカル指標の計算
"""

import pandas as pd


def calculate_vwap(df: pd.DataFrame) -> pd.DataFrame:
    """VWAP（出来高加重平均価格）を計算する。

    典型価格 = (高値 + 安値 + 終値) / 3
    VWAP = 累積(典型価格 × 出来高) / 累積出来高
    """
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    cumulative_tp_vol = (typical_price * df["volume"]).cumsum()
    cumulative_vol = df["volume"].cumsum()
    df["vwap"] = cumulative_tp_vol / cumulative_vol
    return df


def calculate_volume_avg(df: pd.DataFrame, window: int = 5) -> pd.DataFrame:
    """出来高の移動平均を計算する。

    window: 平均を取る期間（本数）
    """
    df["vol_avg"] = df["volume"].rolling(window=window, min_periods=1).mean()
    return df


def calculate_cvd(df: pd.DataFrame) -> pd.DataFrame:
    """CVD（累積出来高デルタ）を計算する。

    陽線（終値 >= 始値）: 出来高を加算（買い圧力）
    陰線（終値 <  始値）: 出来高を減算（売り圧力）
    CVD = そのデルタの累積合計
    """
    delta = df.apply(
        lambda row: row["volume"] if row["close"] >= row["open"] else -row["volume"],
        axis=1,
    )
    df["cvd"] = delta.cumsum()
    return df
