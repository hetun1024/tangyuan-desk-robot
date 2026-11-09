#!/usr/bin/env python3
"""把立绘切成桌面宠物要用的图层。

生成两类东西：
  base_<状态>.png   九个状态整张图
  eyes_00..11.png   只有眼睛的透明叠层（眨眼的 12 帧）
  mouth_00..07.png  只有嘴的透明叠层（说话的 8 帧）

为什么要预先切好：桌面窗口是个 Objective-C 程序，它只负责"把三张图叠起来"，
不做图像处理。切图放在这里做一次，运行时就不需要 Python 了。
"""
from __future__ import annotations

import os
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "assets", "art_clean")
OUT = os.path.join(HERE, "assets", "pet")
S = 720

# 五官在 900×900 立绘里的位置（量出来的）
EYE = (457, 152, 62, 34)
MOUTH = (452, 190, 30, 20)

STATES = {
    "idle": "01_平静", "blink": "02_闭眼", "smile": "03_微笑",
    "surprised": "04_惊讶", "talk": "05_说话", "sad": "06_难过",
    "cry": "07_哭", "angry": "08_生气", "wave": "09_挥手",
}


def load(name: str) -> np.ndarray:
    path = os.path.join(SRC, name + ".png")
    if not os.path.exists(path):
        path = os.path.join(SRC, name + ".webp")
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise FileNotFoundError(path)
    return cv2.resize(img, (S, S), interpolation=cv2.INTER_AREA)


def soft_mask(box) -> np.ndarray:
    cx, cy, rx, ry = [v * S / 900.0 for v in box]
    yy, xx = np.mgrid[0:S, 0:S].astype(np.float32)
    d = np.sqrt(((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2)
    m = np.clip((1.0 - d) / 0.35, 0, 1)
    return cv2.GaussianBlur(m, (0, 0), S * 0.008)


def overlay(src: np.ndarray, mask: np.ndarray, k: float) -> np.ndarray:
    out = src.copy()
    out[:, :, 3] = (mask * k * 255 * (src[:, :, 3] / 255.0)).astype(np.uint8)
    return out


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    try:
        idle, blink, talk = load("01_平静"), load("02_闭眼"), load("05_说话")
    except FileNotFoundError as e:
        print("找不到立绘：%s\n先把图放进 assets/art_clean/" % e)
        return 1

    em, mm = soft_mask(EYE), soft_mask(MOUTH)
    for i in range(12):
        cv2.imwrite(os.path.join(OUT, "eyes_%02d.png" % i), overlay(blink, em, i / 11.0))
    for i in range(8):
        cv2.imwrite(os.path.join(OUT, "mouth_%02d.png" % i), overlay(talk, mm, i / 7.0))
    for key, name in STATES.items():
        try:
            cv2.imwrite(os.path.join(OUT, "base_%s.png" % key), load(name))
        except FileNotFoundError:
            print("缺状态图：%s" % name)

    # 裁到人物本身：所有图层用同一个框，叠起来才不会错位
    ref = cv2.imread(os.path.join(OUT, "base_idle.png"), cv2.IMREAD_UNCHANGED)
    ys, xs = np.where(ref[:, :, 3] > 12)
    if len(xs):
        pad = 6
        x0, x1 = max(0, xs.min() - pad), min(ref.shape[1], xs.max() + pad)
        y0, y1 = max(0, ys.min() - pad), min(ref.shape[0], ys.max() + pad)
        for f in os.listdir(OUT):
            fp = os.path.join(OUT, f)
            im = cv2.imread(fp, cv2.IMREAD_UNCHANGED)
            if im is None:
                continue
            cv2.imwrite(fp, im[y0:y1, x0:x1])
        print("裁到 %dx%d" % (x1 - x0, y1 - y0))

    n = len(os.listdir(OUT))
    size = sum(os.path.getsize(os.path.join(OUT, f)) for f in os.listdir(OUT))
    print("好了：%s 共 %d 个文件，%.1f MB" % (OUT, n, size / 1e6))
    return 0


if __name__ == "__main__":
    sys.exit(main())
