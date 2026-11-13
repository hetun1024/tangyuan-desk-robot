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
KEY_HUE_LO, KEY_HUE_HI = 30, 100      # 绿色的色相范围
KEY_SAT_MIN = 55                     # 饱和度够高才算绿幕
KEY_VAL_MIN = 60


def repair_watermark(frame: np.ndarray) -> np.ndarray:
    """修掉压在裙子上的"豆包AI生成"。

    水印是半透明白字，压在粉色裙摆上：比周围**亮**、而且是灰白（饱和度低）。
    只把笔画那一层用周围颜色补上，不动裙子本身。
    """
    h, w = frame.shape[:2]
    y0, y1 = int(h * 0.88), h
    x0, x1 = int(w * 0.70), w
    roi = frame[y0:y1, x0:x1]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

    bright = hsv[..., 2] > 175
    grayish = hsv[..., 1] < 90
    mask = ((bright & grayish) * 255).astype(np.uint8)
    if mask.sum() == 0:
        return frame
    mask = cv2.dilate(mask, np.ones((3, 3), np.uint8), 1)

    fixed = cv2.inpaint(roi, mask, 4, cv2.INPAINT_TELEA)
    out = frame.copy()
    out[y0:y1, x0:x1] = fixed
    return out


def chroma_key(frame: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    green = ((h >= KEY_HUE_LO) & (h <= KEY_HUE_HI) & (s >= KEY_SAT_MIN) & (v >= KEY_VAL_MIN))
    alpha = np.where(green, 0, 255).astype(np.uint8)

    # 清掉抠图留下的小绿点和毛边，再补上裙子里的小洞
    k = np.ones((3, 3), np.uint8)
    alpha = cv2.morphologyEx(alpha, cv2.MORPH_OPEN, k)     # 去碎点
    alpha = cv2.morphologyEx(alpha, cv2.MORPH_CLOSE, k)    # 补小洞
    alpha = cv2.GaussianBlur(alpha, (3, 3), 0)             # 柔边

    b, g, r = frame[..., 0].astype(np.int16), frame[..., 1].astype(np.int16), frame[..., 2].astype(np.int16)
    # 去绿边：绿通道超过红蓝均值的部分压回去，否则人物边缘会泛绿
    excess = np.clip(g - np.maximum(r, b), 0, 255)
    g = np.clip(g - excess, 0, 255).astype(np.uint8)

    return cv2.merge([b.astype(np.uint8), g, r.astype(np.uint8), alpha])


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
            frames.append(chroma_key(repair_watermark(frame)))
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


# 静态图里人物的归一化位置（量出来的）：头顶在 3.3%，脚底在 97.8%，高占 94.5%
# 动画帧必须按同一比例摆放，否则从静态切到动画时会"胀一下"
TARGET_TOP = 0.033
TARGET_BOTTOM = 0.978
TARGET_CX = 0.507


def fit_to_stage(frame: np.ndarray) -> np.ndarray:
    """把动画帧摆到和静态图一致的"舞台"上：同比例、同底部、同中心。"""
    h, w = frame.shape[:2]
    ys, xs = np.where(frame[..., 3] > 30)
    if len(xs) == 0:
        return frame

    ch = ys.max() - ys.min()
    cw = xs.max() - xs.min()
    # 人物高度要占画布 94.5%
    canvas_h = int(round(ch / (TARGET_BOTTOM - TARGET_TOP)))
    canvas_w = int(round(canvas_h * w / h))
    canvas = np.zeros((canvas_h, canvas_w, 4), np.uint8)

    # 人物底边对齐到画布的 97.8%，中心对齐到 50.7%
    dst_x = int(round(canvas_w * TARGET_CX - cw / 2))
    dst_y = int(round(canvas_h * TARGET_BOTTOM - ch))

    src = frame[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    dst_x = max(0, min(canvas_w - src.shape[1], dst_x))
    dst_y = max(0, min(canvas_h - src.shape[0], dst_y))
    canvas[dst_y:dst_y + src.shape[0], dst_x:dst_x + src.shape[1]] = src
    return canvas


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
    staged = [fit_to_stage(f[y0:y1, x0:x1]) for f in frames]
    size = (staged[0].shape[1], staged[0].shape[0])
    for i, f in enumerate(staged):
        cv2.imwrite(os.path.join(out_dir, "%03d.png" % i),
                    cv2.resize(f, size, interpolation=cv2.INTER_AREA))

    print("写好 %d 帧到 %s" % (len(frames), out_dir))
    print("尺寸 %dx%d" % (x1 - x0, y1 - y0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
