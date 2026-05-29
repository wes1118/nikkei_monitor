"""
notifier.py - Windows デスクトップ通知モジュール
自動発注機能なし。通知のみ。
"""

import importlib.util


def _has_win10toast() -> bool:
    return importlib.util.find_spec("win10toast") is not None


def notify(signal: str, close: float, cvd: int) -> None:
    """最新シグナルが買い・売りのときに Windows 通知を表示する。

    Args:
        signal: "買い" / "売り" / "見送り"
        close:  最新終値
        cvd:    最新 CVD 値
    """
    if signal not in ("買い", "売り"):
        return

    title = f"日経225mini ─ {signal}シグナル"
    message = f"終値: {close:,} 円  |  CVD: {cvd:+,}"

    if _has_win10toast():
        from win10toast import ToastNotifier
        toaster = ToastNotifier()
        toaster.show_toast(
            title,
            message,
            duration=8,
            threaded=True,
        )
    else:
        # win10toast 未インストール時は標準ライブラリの ctypes で代替
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0,
            message,
            title,
            0x00000040,  # MB_ICONINFORMATION
        )
