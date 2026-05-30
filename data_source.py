"""
data_source.py - 市場データの取得
Yahoo Finance（yfinance）経由でリアル市場データを取得する。

【ティッカーの変更方法】
下の TICKER を書き換えるだけで main.py・backtest.py・compare.py すべてに反映されます。

    TICKER = "^N225"   # 日経225指数（デフォルト・常時取得可能、出来高は合成）
    TICKER = "NIY=F"   # 日経225先物 円建て CME E-mini（実出来高・取得できる場合）
    TICKER = "NKD=F"   # 日経225先物 ドル建て CME（実出来高・USD建て注意）
"""

import pandas as pd
import yfinance as yf


# ──────────────────────────────────────────────────────────────────────
# ★ ティッカー設定（ここを変更するだけで全スクリプトに反映される）★
# ──────────────────────────────────────────────────────────────────────

TICKER = "^N225"   # デフォルト: 日経225指数（出来高は合成データ）

# ──────────────────────────────────────────────────────────────────────
# 候補ティッカー一覧（ticker_compare.py の探索に使用）
# ──────────────────────────────────────────────────────────────────────

TICKER_CANDIDATES = [
    ("NIY=F", "日経225先物（円建て・CME E-mini）", "JPY"),
    ("NKD=F", "日経225先物（ドル建て・CME）",       "USD"),
    ("^N225", "日経225インデックス",               "JPY"),
]

# ──────────────────────────────────────────────────────────────────────
# その他の設定
# ──────────────────────────────────────────────────────────────────────

INTERVAL     = "5m"   # 足の種類（yfinance 形式）
PERIOD       = "1d"   # まず直近1日分を試みる
DISPLAY_BARS = 40     # main.py での最大表示本数


# ──────────────────────────────────────────────────────────────────────
# データ取得
# ──────────────────────────────────────────────────────────────────────

def fetch_ohlcv(
    ticker: str   = TICKER,
    period: str   = PERIOD,
    interval: str = INTERVAL,
    limit: int    = DISPLAY_BARS,
    verbose: bool = True,
) -> pd.DataFrame:
    """Yahoo Finance から OHLCV データを取得して返す。

    戻り値: DataFrame（列: datetime / open / high / low / close / volume）
    戻り値のメタデータ（df.attrs）:
        ticker           : 使用したティッカーシンボル
        synthetic_volume : True = 合成出来高 / False = 実出来高
        volume_label     : 表示用文字列（"実データ" / "合成データ（推定値）"）

    引数:
        ticker   - Yahoo Finance のティッカーシンボル
        period   - 取得期間（"1d", "5d", "60d" など）
        interval - 足の種類（"5m", "1h", "1d" など）
        limit    - 末尾から取り出す最大本数（0 = 全件）
        verbose  - False にするとプローブ時のログ出力を抑制
    """
    if verbose:
        print(f"  [{ticker}]  {interval} 足 / {period}  を Yahoo Finance から取得中...")

    tk  = yf.Ticker(ticker)
    raw = tk.history(period=period, interval=interval)

    if raw.empty:
        if verbose:
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

    # 出来高を整数化してタイプを判定
    df["volume"] = df["volume"].fillna(0).astype(int)

    if (df["volume"] == 0).all():
        # 実出来高なし → 価格レンジから合成
        if verbose:
            print("  出来高: 合成データ（価格レンジ×10）"
                  " ※ インデックスには出来高なし → バックテスト精度に制限あり")
        df["volume"] = ((df["high"] - df["low"]) * 10).clip(lower=100).round().astype(int)
        df.attrs["synthetic_volume"] = True
        df.attrs["volume_label"]     = "合成データ（推定値）"
    else:
        avg_vol = df["volume"].mean()
        if verbose:
            print(f"  出来高: 実データあり ✓  （平均 {avg_vol:,.0f} 枚）")
        df.attrs["synthetic_volume"] = False
        df.attrs["volume_label"]     = "実データ"

    df.attrs["ticker"] = ticker

    # 最新 limit 本に絞る
    if limit and len(df) > limit:
        df = df.tail(limit).reset_index(drop=True)

    if verbose:
        s = df["datetime"].iloc[0].strftime("%Y-%m-%d %H:%M")
        e = df["datetime"].iloc[-1].strftime("%Y-%m-%d %H:%M")
        print(f"  {len(df)} 本のデータを取得しました（{s} 〜 {e} JST）")

    return df


# ──────────────────────────────────────────────────────────────────────
# ティッカー探索
# ──────────────────────────────────────────────────────────────────────

def probe_tickers(
    interval: str = INTERVAL,
    period: str   = "5d",
) -> list[dict]:
    """TICKER_CANDIDATES を順に試してデータ取得結果を返す。

    各要素:
        ticker        : ティッカーシンボル
        name          : 日本語名称
        currency      : 建値通貨
        available     : 取得成功 True / 失敗 False
        bars          : 取得バー数
        volume_type   : "実データ" / "合成データ"
        price_avg     : 平均終値（価格スケール確認用）
        error         : 失敗時のエラーメッセージ（省略）
    """
    results = []
    for ticker, name, currency in TICKER_CANDIDATES:
        try:
            df = fetch_ohlcv(
                ticker=ticker,
                period=period,
                interval=interval,
                limit=0,
                verbose=False,
            )
            vol_type = "合成データ" if df.attrs.get("synthetic_volume") else "実データ"
            results.append({
                "ticker":      ticker,
                "name":        name,
                "currency":    currency,
                "available":   True,
                "bars":        len(df),
                "volume_type": vol_type,
                "price_avg":   df["close"].mean(),
            })
        except Exception as e:
            results.append({
                "ticker":    ticker,
                "name":      name,
                "currency":  currency,
                "available": False,
                "error":     str(e)[:80],
            })
    return results
