#!/usr/bin/env python3
"""把一段绿幕视频变成桌宠能播的动画。

    python3 pet/make_anim.py 视频.mp4 idle
    python3 pet/make_anim.py 视频.mp4 wave

做四件事：
  1. 抽帧（默认 20fps，够顺又不占地方）
  2. HSV 抠绿幕 + 去绿边（不去的会有一圈绿毛）
  3. 所有动作**共用同一个裁切框**（从第一个动作算出来），保证换动作时不跳
  4. 存成 assets/pet/anim/<名字>/000.png …

为什么要共用裁切框：每个视频单独裁的话，人物在不同动作里会忽大忽小、
位置左右跳，播起来就像在抽搐。
"""
from __future__ import annotations

import os
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_ROOT = os.path.join(HERE, "assets", "pet", "anim")
BOX_FILE = os.path.join(HERE, "assets", "pet", "anim_box.txt")

FPS = 20
KEY_HUE_LO, KEY_HUE_HI = 35, 95      # 绿色的色相范围
KEY_SAT_MIN = 70                     # 饱和度够高才算绿幕
KEY_VAL_MIN = 60


def chroma_key(frame: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    green = ((h >= KEY_HUE_LO) & (h <= KEY_HUE_HI) & (s >= KEY_SAT_MIN) & (v >= KEY_VAL_MIN))
    alpha = np.where(green, 0, 255).astype(np.uint8)

    # 边缘一像素半透明，避免锯齿
    alpha = cv2.GaussianBlur(alpha, (3, 3), 0)

    b, g, r = frame[..., 0].astype(np.int16), frame[..., 1].astype(np.int16), frame[..., 2].astype(np.int16)
    # 去绿边：绿通道超过红蓝均值的部分压回去，否则人物边缘会泛绿
    excess = np.clip(g - np.maximum(r, b), 0, 255)
    g = np.clip(g - excess, 0, 255).astype(np.uint8)

    out = cv2.merge([b.astype(np.uint8), g, r.astype(np.uint8), alpha])
    return out


def content_box(frames_rgba) -> tuple:
    """所有帧的并集裁切框（留一点边）。"""
    x0 = y0 = 10**9
    x1 = y1 = -1
    for f in frames_rgba:
        ys, xs = np.where(f[..., 3] > 30)
        if len(xs) == 0:
            continue
        x0, x1 = min(x0, xs.min()), max(x1, xs.max())
        y0, y1 = min(y0, ys.min()), max(y1, ys.max())
    if x1 < 0:
        h, w = frames_rgba[0].shape[:2]
        return 0, 0, w, h
    pad = 4
    h, w = frames_rgba[0].shape[:2]
    return max(0, x0 - pad), max(0, y0 - pad), min(w, x1 + pad), min(h, y1 + pad)


def read_video(path: str):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise SystemExit("打不开视频：%s" % path)
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30
    step = max(1, int(round(src_fps / FPS)))
    frames = []
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if i % step == 0:
            frames.append(chroma_key(frame))
        i += 1
    cap.release()
    return frames


def save_box(box) -> None:
    os.makedirs(os.path.dirname(BOX_FILE), exist_ok=True)
    with open(BOX_FILE, "w") as fh:
        fh.write("%d %d %d %d\n" % box)


def load_box():
    if not os.path.exists(BOX_FILE):
        return None
    try:
        return tuple(int(v) for v in open(BOX_FILE).read().split())
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    src, name = sys.argv[1], sys.argv[2].strip()

    print("读视频…")
    frames = read_video(src)
    if not frames:
        print("视频里没有帧")
        return 1
    print("抽到 %d 帧" % len(frames))

    box = load_box()
    if box is None:
        box = content_box(frames)
        save_box(box)
        print("第一次跑，用这段视频定裁切框：%s" % (box,))
    else:
        print("沿用已有裁切框：%s" % (box,))

    x0, y0, x1, y1 = box
    out_dir = os.path.join(OUT_ROOT, name)
    os.makedirs(out_dir, exist_ok=True)
    for i, f in enumerate(frames):
        cv2.imwrite(os.path.join(out_dir, "%03d.png" % i), f[y0:y1, x0:x1])

    print("写好 %d 帧到 %s" % (len(frames), out_dir))
    print("尺寸 %dx%d" % (x1 - x0, y1 - y0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
