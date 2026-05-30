"""
indicators.py - テクニカル指標の計算
"""

import pandas as pd


def calculate_ema(df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """EMA（指数移動平均）を計算する。

    window: EMA の期間（デフォルト 20本 = 5分足なら約100分）
    終値が EMA より上 → 上昇トレンド、下 → 下降トレンドの判断に使う。
    min_periods=1 で最初のバーから計算を開始する（ゼロ埋めなし）。
    """
    df["ema"] = df["close"].ewm(span=window, adjust=False, min_periods=1).mean()
    return df


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """ATR（平均真値幅）を計算する。

    True Range = 以下の最大値:
        high - low
        |high - 前足の close|
        |low  - 前足の close|
    ATR = True Range の period 本移動平均

    ATR が大きい → ボラティリティが高い（動きが大きい）
    ATR が小さい → ボラティリティが低い（レンジ・膠着）
    """
    prev_close = df["close"].shift(1)
    true_range = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"]  - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    df["atr"] = true_range.rolling(window=period, min_periods=1).mean()
    return df


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
