"""
strategy.py - 売買シグナルの判定ロジック
"""

import pandas as pd


def _judge_row(row: pd.Series) -> str:
    """1本分のローソク足データからシグナルを判定する。

    買い条件:
        - 終値が VWAP より上（日中の買い優勢）
        - CVD が正（累積で買い圧力が強い）
        - 出来高が平均を超えている（動きを確認）

    売り条件:
        - 終値が VWAP より下（日中の売り優勢）
        - CVD が負（累積で売り圧力が強い）
        - 出来高が平均を超えている（動きを確認）

    それ以外: 見送り
    """
    price_above_vwap = row["close"] > row["vwap"]
    price_below_vwap = row["close"] < row["vwap"]
    cvd_positive = row["cvd"] > 0
    cvd_negative = row["cvd"] < 0
    high_volume = row["volume"] > row["vol_avg"]

    if price_above_vwap and cvd_positive and high_volume:
        return "買い"
    elif price_below_vwap and cvd_negative and high_volume:
        return "売り"
    else:
        return "見送り"


def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    """全行にシグナル判定を適用してシグナル列を追加する。"""
    df["signal"] = df.apply(_judge_row, axis=1)
    return df
