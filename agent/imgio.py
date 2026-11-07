"""读写图片时绕开 cv2 的老毛病：路径里有中文就读不到/存不下。"""
from __future__ import annotations

import cv2
import numpy as np


def imread(path: str, flags: int = cv2.IMREAD_COLOR):
    try:
        data = np.fromfile(path, dtype=np.uint8)
    except OSError:
        return None
    if data.size == 0:
        return None
    return cv2.imdecode(data, flags)


def imwrite(path: str, img) -> bool:
    ext = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ".png"
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        return False
    try:
        buf.tofile(path)
    except OSError:
        return False
    return True
