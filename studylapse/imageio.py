"""Unicode-safe image read/write (cv2.imread/imwrite break on non-ASCII Windows paths)."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def write_jpeg(path: Path, img: np.ndarray, quality: int = 90) -> bool:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, int(quality)])
    if not ok:
        return False
    Path(path).write_bytes(buf.tobytes())
    return True


def read_image(path: Path) -> np.ndarray | None:
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def thumbnail(img: np.ndarray | None, width: int = 720) -> np.ndarray | None:
    if img is None:
        return None
    h, w = img.shape[:2]
    if w <= width:
        return img.copy()
    return cv2.resize(img, (width, int(h * width / w)), interpolation=cv2.INTER_AREA)
