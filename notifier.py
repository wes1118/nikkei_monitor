"""
notifier.py - Windows デスクトップ通知モジュール
自動発注機能なし。通知のみ。
"""

import ctypes


def notify(signal: str, close: float, cvd: int) -> None:
    """最新シグナルが買い・売りのときに Windows メッセージボックスを表示する。

    Args:
        signal: "買い" / "売り" / "見送り"
        close:  最新終値
        cvd:    最新 CVD 値
    """
    if signal not in ("買い", "売り"):
        return

    title = f"日経225mini ─ {signal}シグナル"
    message = f"終値: {close:,} 円  |  CVD: {cvd:+,}"

    ctypes.windll.user32.MessageBoxW(
        0,
        message,
        title,
        0x00000040,  # MB_ICONINFORMATION
    )
