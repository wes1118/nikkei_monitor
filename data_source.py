"""
data_source.py - 市場データの取得
Yahoo Finance（yfinance）経由でリアル市場データを取得する。

対象ティッカー:
    ^N225  日経225インデックス（JPY建て、常時無料取得可能）
           ※ 日経225mini 先物（OSE 上場）は無料 API では取得困難なため
             開発用として指数データを使用する。
           ※ 将来的に先物データへ切り替える場合は TICKER を変更するだけでよい。
"""

import pandas as pd
import yfinance as yf

TICKER        = "^N225"   # 日経225インデックス
INTERVAL      = "5m"      # 5分足
PERIOD        = "1d"      # まず直近1日分を試みる
DISPLAY_BARS  = 40        # 最大表示本数（多すぎるとターミナルが見づらいため）


def fetch_ohlcv(
    ticker: str   = TICKER,
    period: str   = PERIOD,
    interval: str = INTERVAL,
    limit: int    = DISPLAY_BARS,
) -> pd.DataFrame:
    """Yahoo Finance から OHLCV データを取得して返す。

    戻り値のカラム:
        datetime  - タイムスタンプ（JST、タイムゾーンなし）
        open      - 始値
        high      - 高値
        low       - 安値
        close     - 終値
        volume    - 出来高

    引数:
        ticker   - Yahoo Finance のティッカーシンボル（デフォルト: "^N225"）
        period   - 取得期間（yfinance 形式: "1d", "5d", "1mo" など）
        interval - 足の種類（yfinance 形式: "1m", "5m", "1h", "1d" など）
        limit    - 末尾から取り出す最大本数（0 = 全件）
    """
    print(f"  [{ticker}]  {interval} 足 / {period}  を Yahoo Finance から取得中...")

    tk = yf.Ticker(ticker)
    raw = tk.history(period=period, interval=interval)

    # 当日がまだ開場前・休場の場合は直近5日分を再取得
    if raw.empty:
        print("  当日データなし。直近5日間のデータを再取得します...")
        raw = tk.history(period="5d", interval=interval)

    if raw.empty:
        raise RuntimeError(
            f"データを取得できませんでした: {ticker}\n"
            "インターネット接続と ticker シンボルを確認してください。"
        )

    # タイムゾーンを JST に変換してからナイーブな datetime に変換
    if raw.index.tz is not None:
        raw.index = raw.index.tz_convert("Asia/Tokyo").tz_localize(None)

    # 必要なカラムのみ選択・小文字にリネーム
    df = raw[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.columns = ["open", "high", "low", "close", "volume"]
    df.index.name = "datetime"
    df = df.reset_index()

    # NaN 行を除去
    df = df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)

    # 出来高を整数化
    df["volume"] = df["volume"].fillna(0).astype(int)

    # 出来高が全て 0 の場合（指数データに多い）: 価格レンジから合成出来高を生成
    if (df["volume"] == 0).all():
        print("  出来高データなし → 価格レンジから合成出来高を生成します（開発用近似値）。")
        df["volume"] = ((df["high"] - df["low"]) * 10).clip(lower=100).round().astype(int)

    # 最新 limit 本に絞る
    if limit and len(df) > limit:
        df = df.tail(limit).reset_index(drop=True)

    start_str = df["datetime"].iloc[0].strftime("%Y-%m-%d %H:%M")
    end_str   = df["datetime"].iloc[-1].strftime("%Y-%m-%d %H:%M")
    print(f"  {len(df)} 本のデータを取得しました（{start_str} 〜 {end_str} JST）")

    return df
