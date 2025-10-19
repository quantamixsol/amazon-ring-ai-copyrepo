import os
from app.config import LOGO_CANDIDATES


def get_logo_path() -> str | None:
    for p in LOGO_CANDIDATES:
        try:
            if os.path.exists(p):
                return p
        except Exception:
            pass
    return None