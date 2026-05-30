"""
session_filter.py - セッション（取引時間帯）フィルター
5分足データを指定した取引時間帯のバーのみに絞り込む。

【セッションの変更方法】
下の SESSION を書き換えるだけで backtest.py・ticker_compare.py に反映されます。

    SESSION = "all_sessions"    # フィルターなし（デフォルト）
    SESSION = "day_session"     # 日中セッション 08:45〜15:15 JST
    SESSION = "night_session"   # 夜間セッション 16:30〜翌06:00 JST

※ 夜間セッションは日付をまたぐため、VWAP/CVD の日次リセットが暦日（JST 00:00）で
   区切られます。正確な夜間セッション単位でのリセットは未対応（簡易実装）。
※ ^N225（日経225指数）は日本市場時間のみのデータです。
   night_session を使う場合は NIY=F など先物ティッカーを推奨します。
"""

from datetime import time
import pandas as pd


# ──────────────────────────────────────────────────────────────────────
# ★ セッション設定（ここを変更するだけで全スクリプトに反映される）★
# ──────────────────────────────────────────────────────────────────────

SESSION = "all_sessions"   # "day_session" / "night_session" / "all_sessions"


# ──────────────────────────────────────────────────────────────────────
# セッション定義（参照用・変更不要）
# ──────────────────────────────────────────────────────────────────────

SESSIONS: dict[str, dict] = {
    "all_sessions": {
        "label": "全セッション",
        "desc":  "フィルターなし（全バーを対象）",
        "start": None,
        "end":   None,
    },
    "day_session": {
        "label": "日中セッション",
        "desc":  "08:45〜15:15 JST（日本市場・大阪取引所）",
        "start": time(8,  45),
        "end":   time(15, 15),
    },
    "night_session": {
        "label": "夜間セッション",
        "desc":  "16:30〜翌06:00 JST（欧米市場時間帯）",
        "start": time(16, 30),
        "end":   time(6,  0),
    },
}

# セッション名のリスト（比較スクリプトが参照）
ALL_SESSION_KEYS = ["all_sessions", "day_session", "night_session"]


# ──────────────────────────────────────────────────────────────────────
# フィルター関数
# ──────────────────────────────────────────────────────────────────────

def filter_session(df: pd.DataFrame, session: str = "all_sessions") -> pd.DataFrame:
    """指定セッションのバーのみ抽出して返す。

    引数:
        df      - datetime 列を持つ OHLCV DataFrame
        session - "all_sessions" / "day_session" / "night_session"

    戻り値:
        フィルター済み DataFrame（インデックスはリセット済み）
        空になった場合は空の DataFrame を返す（呼び出し元で確認すること）
    """
    if session not in SESSIONS:
        raise ValueError(
            f"不明なセッション: '{session}'  有効値: {list(SESSIONS.keys())}"
        )

    if session == "all_sessions":
        return df.reset_index(drop=True)

    t   = df["datetime"].dt.time
    cfg = SESSIONS[session]

    if session == "day_session":
        # 08:45 以上かつ 15:15 以下
        mask = (t >= cfg["start"]) & (t <= cfg["end"])

    elif session == "night_session":
        # 日付をまたぐ: 16:30 以降 OR 06:00 以前
        mask = (t >= cfg["start"]) | (t <= cfg["end"])

    else:
        mask = pd.Series([True] * len(df), index=df.index)

    filtered = df[mask].reset_index(drop=True)
    return filtered


# ──────────────────────────────────────────────────────────────────────
# 表示ヘルパー
# ──────────────────────────────────────────────────────────────────────

def session_label(session: str) -> str:
    """セッションの短い日本語ラベルを返す。例: "日中セッション" """
    return SESSIONS.get(session, {}).get("label", session)


def session_desc(session: str) -> str:
    """セッションの説明文を返す。例: "08:45〜15:15 JST..." """
    return SESSIONS.get(session, {}).get("desc", "")
