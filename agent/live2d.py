"""汤圆的身体：一张会呼吸、会眨眼、会说话的立绘。

不是 Live2D，但原理一样 —— **同一套图的多个状态之间做混合**。

    平静   ←基础
    闭眼   ←眨眼时混进来
    说话   ←说话时混进来
    微笑 / 难过 / 哭 / 生气 / 惊讶 / 挥手  ←整体换表情

为什么不切片只换眼睛：这十张是整张生成的，眼睛和嘴没法单独抠出来对齐。
整张混合反而更稳 —— 构图够齐，混起来看不出来，而且换美术时只要换十张图。

呼吸和微晃是**变换**不是新图：整张轻轻缩放、平移一点，人就活过来了。
"""
from __future__ import annotations

import os
from typing import Dict, Optional

import cv2
import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(HERE, "assets", "art_clean")

# 文件名 → 内部名字
FILES = {
    "idle": "01_平静",
    "blink": "02_闭眼",
    "smile": "03_微笑",
    "surprised": "04_惊讶",
    "talk": "05_说话",
    "sad": "06_难过",
    "cry": "07_哭",
    "angry": "08_生气",
    "wave": "09_挥手",
}

# 五官在 900×900 立绘里的位置（量出来的，不是猜的）
#   cx, cy, rx, ry —— 用椭圆是因为边缘要柔，硬边会有接缝
EYE = (457, 152, 62, 34)      # 两只眼
MOUTH = (452, 188, 30, 18)    # 嘴
HEAD = (452, 190, 120, 130)   # 整个头，换表情时只动这一块

# 情绪 → 用哪张图
MOODS = {
    "idle": "idle", "listening": "idle", "thinking": "idle",
    "happy": "smile", "love": "smile", "star": "smile",
    "talking": "idle", "surprised": "surprised",
    "sad": "sad", "cry": "cry", "angry": "angry",
    "sleepy": "blink", "question": "surprised",
    "wave": "wave", "hello": "wave", "bye": "wave",
}


def _bg(w: int, h: int) -> np.ndarray:
    """深紫背景，中间一团柔光 —— 和立绘的影棚感对得上。"""
    img = np.zeros((h, w, 3), np.uint8)
    top, bot = (46, 34, 54), (20, 16, 26)
    for y in range(h):
        k = y / h
        img[y, :] = [int(top[i] + (bot[i] - top[i]) * k) for i in range(3)]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.sqrt((xx - w / 2) ** 2 + (yy - h * 0.30) ** 2) / (w * 0.62)
    glow = (np.clip(1 - d, 0, 1) ** 2 * 26).astype(np.uint8)[..., None]
    return np.clip(img.astype(np.int16) + glow, 0, 255).astype(np.uint8)


class Model:
    def __init__(self, art_dir: str = ART, size: int = 480):
        self.size = size
        self.frames: Dict[str, np.ndarray] = {}
        for key, name in FILES.items():
            path = os.path.join(art_dir, name + ".webp")
            if not os.path.exists(path):
                path = os.path.join(art_dir, name + ".png")
            if not os.path.exists(path):
                continue
            img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
            if img is None:
                continue
            self.frames[key] = self._fit(img)
        if "idle" not in self.frames:
            raise FileNotFoundError("找不到立绘：%s" % art_dir)
        self.bg = _bg(self.size, self.size)
        self.eye_mask = self._ellipse_mask(self.size, EYE)
        self.mouth_mask = self._ellipse_mask(self.size, MOUTH)
        self.head_mask = self._ellipse_mask(self.size, HEAD, feather=0.5)

    @staticmethod
    def _ellipse_mask(size: int, box, feather: float = 0.35) -> np.ndarray:
        """柔边的椭圆遮罩（0..1）。feather 越大边缘越糊。"""
        cx, cy, rx, ry = [v * size / 900.0 for v in box]
        yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
        d = np.sqrt(((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2)
        inner = 1.0 - feather
        m = np.clip((1.0 - d) / max(feather, 1e-3), 0, 1)
        return cv2.GaussianBlur(m, (0, 0), size * 0.006)

    def _region_mix(self, a: np.ndarray, b: np.ndarray, k: float,
                    mask: np.ndarray) -> np.ndarray:
        """只在遮罩范围内混合 b，其他地方**一个像素都不动**。"""
        if k <= 0.001:
            return a
        w = (mask * min(1.0, k))[..., None]
        pa = a.astype(np.float32)
        pb = b.astype(np.float32)
        out = pa.copy()
        out[..., :3] = pa[..., :3] * (1 - w) + pb[..., :3] * w
        out[..., 3] = pa[..., 3] * (1 - w[..., 0]) + pb[..., 3] * w[..., 0]
        return out.astype(np.uint8)

    def _fit(self, img: np.ndarray) -> np.ndarray:
        """缩放到画布大小，等比缩放、居中。"""
        h, w = img.shape[:2]
        s = self.size / max(h, w)
        nw, nh = int(w * s), int(h * s)
        img = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
        canvas = np.zeros((self.size, self.size, 4), np.uint8)
        y0 = (self.size - nh) // 2
        x0 = (self.size - nw) // 2
        canvas[y0 : y0 + nh, x0 : x0 + nw] = img
        return canvas

    # ------------------------------------------------------------ 混合
    @staticmethod
    def _mix(a: np.ndarray, b: np.ndarray, k: float) -> np.ndarray:
        """按 alpha 正确混合两张 RGBA（预乘再混，边缘不会发黑）。"""
        k = float(np.clip(k, 0.0, 1.0))
        if k <= 0.001:
            return a
        if k >= 0.999:
            return b
        pa = a.astype(np.float32)
        pb = b.astype(np.float32)
        aa = pa[..., 3:4] / 255.0
        ab = pb[..., 3:4] / 255.0
        rgb = pa[..., :3] * aa * (1 - k) + pb[..., :3] * ab * k
        al = aa * (1 - k) + ab * k
        out = np.zeros_like(pa)
        out[..., :3] = np.where(al > 1e-4, rgb / np.maximum(al, 1e-4), 0)
        out[..., 3] = al[..., 0] * 255
        return out.astype(np.uint8)

    # ------------------------------------------------------------ 一帧
    def frame(self, mood: str = "idle", t: float = 0.0,
              blink: float = 0.0, talk: float = 0.0,
              fade: Optional[np.ndarray] = None) -> np.ndarray:
        """mood 是情绪名；blink/talk 是 0..1 的混合权重。

        身体永远不动 —— 只在眼睛、嘴、头这三块地方做混合。
        整张混会让身体轻轻飘，看起来像在闪。
        """
        key = MOODS.get(mood, "idle")
        base = self.frames.get(key, self.frames["idle"])

        if fade is not None:
            base = self._region_mix(fade, base, 0.35, self.head_mask)

        if blink > 0.01 and "blink" in self.frames:
            base = self._region_mix(base, self.frames["blink"], blink, self.eye_mask)
        if talk > 0.01 and "talk" in self.frames:
            base = self._region_mix(base, self.frames["talk"], talk, self.mouth_mask)

        alpha = (base[..., 3:4].astype(np.float32) / 255.0)
        rgb = base[..., :3].astype(np.float32)
        out = rgb * alpha + self.bg.astype(np.float32) * (1 - alpha)
        return out.astype(np.uint8)

    def has(self, mood: str) -> bool:
        return MOODS.get(mood, "idle") in self.frames
