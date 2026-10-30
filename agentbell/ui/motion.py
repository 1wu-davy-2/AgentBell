from __future__ import annotations

import os
import sys

_SPI_GETCLIENTAREAANIMATION = 0x1042


def motion_enabled() -> bool:
    override = os.environ.get("AGENTBELL_MOTION", "").strip().lower()
    if override in {"0", "false", "off", "no", "reduced"}:
        return False
    if override in {"1", "true", "on", "full"}:
        return True
    if sys.platform == "win32":
        try:
            import ctypes

            enabled = ctypes.c_int(1)
            ok = ctypes.windll.user32.SystemParametersInfoW(
                _SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(enabled), 0
            )
            if ok:
                return bool(enabled.value)
        except Exception:
            pass
    return True
