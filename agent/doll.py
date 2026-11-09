"""汤圆的身体：一个宫廷风的洋娃娃。

为什么不用 Live2D：
  .moc3 是 Cubism Editor 手工拆图层、画网格、绑参数才能生成的格式，
  没有那个软件就做不出来，代码也生成不了。

所以这里换了条路：**用代码分层画**。结果是同一个东西——
  一层一层的（后发 / 裙子 / 身体 / 脸 / 眼睛 / 刘海 / 配饰），
  每个部位由参数驱动，参数一动就有表情和动作。
分层的顺序就是 Live2D 的图层顺序，将来真要用 Cubism 重做，
这份代码就是现成的拆分稿。

参数 p 是一堆 0..1 的数（见 DEFAULTS），
draw() 把参数变成一张图。没有状态，方便测。
"""
from __future__ import annotations

import math
from typing import Dict

import numpy as np

# 设计尺寸：所有坐标都按这个来，最后统一缩放
W, H = 420, 600

# 调色：宫廷复古洋娃娃
SKIN = (222, 232, 250)
SKIN_SHADOW = (200, 210, 236)
BLUSH = (160, 160, 246)
HAIR = (150, 205, 238)
HAIR_LIGHT = (185, 228, 250)
HAIR_DARK = (115, 168, 210)
HAIR_GLOW = (215, 240, 255)
EYE_WHITE = (250, 250, 252)
IRIS_TOP = (150, 105, 70)
IRIS_BOT = (205, 165, 105)
PUPIL = (62, 44, 30)
LASH = (78, 62, 58)
BROW = (120, 165, 205)
LIP = (130, 130, 232)
LIP_DARK = (105, 100, 205)
DRESS = (196, 208, 248)
DRESS_DARK = (168, 176, 228)
LACE = (248, 248, 255)
GOLD = (150, 205, 240)
PEARL = (238, 244, 252)
BG_TOP = (44, 34, 52)
BG_BOT = (22, 18, 30)

DEFAULTS: Dict[str, float] = {
    "eye_open": 1.0,      # 睁眼程度
    "eye_scale": 1.0,     # 整体缩放（惊讶时变大）
    "gaze_x": 0.0,        # 视线左右 -1..1
    "gaze_y": 0.0,        # 视线上下 -1..1
    "brow": 0.0,          # 眉毛高度 -1..1
    "mouth_open": 0.0,    # 张嘴 0..1
    "mouth_curve": 0.35,  # 嘴角 -1（垮）..1（笑）
    "mouth_w": 1.0,       # 嘴宽
    "blush": 0.35,        # 腮红
    "tear": 0.0,          # 眼泪
    "head_dx": 0.0,       # 头左右偏（像素，设计坐标）
    "head_dy": 0.0,
    "tilt": 0.0,          # 歪头（度）
    "arm_l": 0.0,         # 左手抬起 0..1
    "arm_r": 0.0,
    "breath": 1.0,        # 呼吸幅度 0..1
}


def _p(**kw) -> dict:
    p = dict(DEFAULTS)
    p.update(kw)
    return p


# ---------------------------------------------------------------- 基础画法
def _poly(img, pts, color, ss):
    import cv2

    arr = (np.array(pts) * ss).astype(np.int32)
    cv2.fillPoly(img, [arr], color, cv2.LINE_AA)


def _ell(img, c, axes, color, ss, angle=0.0):
    import cv2

    cv2.ellipse(img, (int(c[0] * ss), int(c[1] * ss)),
                (int(axes[0] * ss), int(axes[1] * ss)), angle, 0, 360, color, -1, cv2.LINE_AA)


def _arc(img, c, axes, color, thick, ss, a0=0, a1=360, angle=0.0):
    import cv2

    cv2.ellipse(img, (int(c[0] * ss), int(c[1] * ss)),
                (int(axes[0] * ss), int(axes[1] * ss)), angle, a0, a1, color,
                max(1, int(thick * ss)), cv2.LINE_AA)


def _line(img, pts, color, thick, ss):
    import cv2

    arr = (np.array(pts) * ss).astype(np.int32)
    cv2.polylines(img, [arr], False, color, max(1, int(thick * ss)), cv2.LINE_AA)


def _wavy(top_y, cx, half_w, amp, freq, n=40, phase=0.0):
    """生成一条波浪底边（用于刘海、裙摆）。"""
    pts = [(cx - half_w, top_y - amp * 1.4)]
    for i in range(n + 1):
        k = i / n
        x = cx - half_w + 2 * half_w * k
        y = top_y + amp * math.sin(k * freq * math.pi + phase)
        pts.append((x, y))
    pts.append((cx + half_w, top_y - amp * 1.4))
    return pts


def _radial(size, center, radius, color, strength=1.0):
    """柔和径向光斑（腮红、高光都用它）。"""
    import cv2

    h, w = size
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.sqrt((xx - center[0]) ** 2 + (yy - center[1]) ** 2) / max(radius, 1e-3)
    a = np.clip(1.0 - d, 0, 1) ** 2 * strength
    layer = np.zeros((h, w, 3), np.uint8)
    layer[:] = color
    return layer, (a * 255).astype(np.uint8)


def _blend(img, layer, mask):
    import cv2

    m = (mask.astype(np.float32) / 255.0)[..., None]
    return (img.astype(np.float32) * (1 - m) + layer.astype(np.float32) * m).astype(np.uint8)


# ---------------------------------------------------------------- 脸型
def _face_outline(cx, cy, rx, ry, n=72):
    """洋娃娃的脸：上半圆润，下半收成尖下巴。"""
    pts = []
    for i in range(n + 1):
        a = -math.pi + 2 * math.pi * i / n
        x = math.cos(a)
        y = math.sin(a)
        taper = 1.0
        if y > 0:  # 下半张脸往中间收
            taper = 1.0 - 0.30 * (y ** 1.4)
        pts.append((cx + rx * x * taper, cy + ry * y))
    return pts


# ---------------------------------------------------------------- 眼睛
def _eye(img, cx, cy, w, h, p, side, ss):
    """画一只眼睛。side=-1 左眼，1 右眼。"""
    open_ = max(0.0, min(1.0, p["eye_open"]))
    w *= p["eye_scale"]
    h *= p["eye_scale"] * max(open_, 0.02)

    _ell(img, (cx, cy), (w, max(h, 1.6)), EYE_WHITE, ss, angle=-3 * side)
    if h < 3:
        _line(img, [(cx - w, cy), (cx + w * 0.15, cy + 1.5 * side),
                    (cx + w, cy - 1)], LASH, 2.4, ss)
        return

    ix = cx + p["gaze_x"] * w * 0.26
    iy = cy + p["gaze_y"] * h * 0.20
    ir = min(w, h) * 0.94
    _ell(img, (ix, iy), (ir * 0.80, ir), IRIS_TOP, ss)
    _ell(img, (ix, iy + ir * 0.32), (ir * 0.72, ir * 0.60), IRIS_BOT, ss)
    _ell(img, (ix, iy + ir * 0.12), (ir * 0.38, ir * 0.56), PUPIL, ss)
    _ell(img, (ix - ir * 0.32, iy - ir * 0.40), (ir * 0.24, ir * 0.28), (255, 255, 255), ss)
    _ell(img, (ix + ir * 0.28, iy + ir * 0.32), (ir * 0.13, ir * 0.15), (245, 250, 255), ss)

    # 上睫毛：贴着上眼睑，眼角往外翘
    pts = []
    for i in range(21):
        k = i / 20
        x = cx - w + 2 * w * k
        y = cy - h * (0.60 + 0.40 * math.sin(k * math.pi))
        pts.append((x, y))
    _line(img, pts, LASH, 3.6, ss)
    tip = (cx + side * w * 1.22, cy - h * 0.72)
    _line(img, [pts[-1] if side > 0 else pts[0], tip], LASH, 2.8, ss)

    low = []
    for i in range(9):
        k = i / 8
        x = cx - w * 0.70 + 1.40 * w * k
        y = cy + h * 0.84 - h * 0.08 * math.sin(k * math.pi)
        low.append((x, y))
    _line(img, low, LASH, 1.3, ss)


# ---------------------------------------------------------------- 主绘制
def draw(p: dict, t: float = 0.0, blink: float = 1.0, size: int = 420) -> np.ndarray:
    """参数 + 时间 → 一张 BGR 图。blink 是 0..1（1 完全睁开）。"""
    import cv2

    ss = 2
    w, h = W * ss, H * ss
    img = np.zeros((h, w, 3), np.uint8)

    # 背景
    for y in range(H):
        k = y / H
        c = tuple(int(BG_TOP[i] + (BG_BOT[i] - BG_TOP[i]) * k) for i in range(3))
        cv2.line(img, (0, y * ss), (w, y * ss + ss), c, ss)
    layer, mask = _radial((h, w), (W * ss * 0.5, H * ss * 0.30), W * ss * 0.66, (74, 58, 88), 0.95)
    img = _blend(img, layer, mask)

    breath = math.sin(t * 1.1) * 2.0 * p["breath"]
    sway = math.sin(t * 0.42) * 2.6 * p["breath"]
    hdx = p["head_dx"] + sway * 0.55
    hdy = p["head_dy"] + breath * 0.4
    tilt = p["tilt"]

    head_c = (210 + hdx, 258 + hdy)
    RX, RY = 94.0, 98.0

    def rot(pt, origin=head_c, deg=tilt):
        a = math.radians(deg)
        ca, sa = math.cos(a), math.sin(a)
        dx, dy = pt[0] - origin[0], pt[1] - origin[1]
        return (origin[0] + dx * ca - dy * sa, origin[1] + dx * sa + dy * ca)

    def hp(pt):
        return rot(pt)

    # ---------------- 后发：脑后的一大片
    back = _face_outline(head_c[0], head_c[1] - 6, 128, 132, 60)
    back = [hp(q) for q in back]
    back += [hp((320, 590)), hp((100, 590))]
    _poly(img, back, HAIR_DARK, ss)

    # ---------------- 双丸子（贴在头两侧偏上）
    for side, bx in ((-1, 104), (1, 316)):
        c = hp((bx, 186))
        _ell(img, c, (56, 54), HAIR_DARK, ss)
        _ell(img, (c[0] - side * 3, c[1] - 3), (52, 50), HAIR, ss)
        for k in range(3):
            r = 40 - k * 12
            _arc(img, (c[0] - 5 + k * 4, c[1] + 2 * k), (r, r * 0.9),
                 HAIR_DARK if k % 2 == 0 else HAIR_LIGHT, 1.8, ss, 205, 335, angle=20 * side)
        _ell(img, (c[0] - 16, c[1] - 18), (20, 15), HAIR_GLOW, ss)

    # ---------------- 脖子和肩
    _poly(img, [hp((188, 352)), hp((232, 352)), hp((236, 424)), hp((184, 424))], SKIN, ss)
    _poly(img, [hp((188, 352)), hp((232, 352)), hp((231, 382)), hp((189, 382))], SKIN_SHADOW, ss)

    # ---------------- 裙子
    _poly(img, [(60, 474), (150, 432), (270, 432), (360, 474),
                (388, 600), (32, 600)], DRESS, ss)
    # 泡泡袖
    for sc in ((88, 492), (332, 492)):
        c = (sc[0], sc[1] + breath * 0.3)
        _ell(img, c, (56, 50), DRESS, ss)
        _arc(img, c, (56, 50), DRESS_DARK, 1.6, ss)
        for k in range(4):
            a = 0.15 * math.pi + 0.23 * k * math.pi
            _arc(img, (c[0] + math.cos(a) * 40, c[1] + math.sin(a) * 34),
                 (16, 13), LACE, 1.4, ss, 195, 345)

    # 胸衣
    _poly(img, [(150, 434), (270, 434), (284, 552), (136, 552)], DRESS, ss)
    _line(img, [(150, 434), (136, 552)], DRESS_DARK, 1.4, ss)
    _line(img, [(270, 434), (284, 552)], DRESS_DARK, 1.4, ss)
    # 蕾丝领口
    _poly(img, [(150, 434), (270, 434), (266, 452), (154, 452)], LACE, ss)
    for k in range(7):
        _arc(img, (162 + k * 16, 452), (8, 6), LACE, 1.2, ss, 0, 180)
    # 束腰的深色带
    _poly(img, [(140, 520), (280, 520), (284, 552), (136, 552)], DRESS_DARK, ss)
    _poly(img, [(140, 520), (280, 520), (281, 528), (139, 528)], LACE, ss)

    # 裙摆褶
    for k, (yy, amp, col) in enumerate(((566, 8, LACE), (582, 11, DRESS_DARK), (596, 13, LACE))):
        _line(img, _wavy(yy, 210, 178 - k * 5, amp, 9, phase=k), col, 2.6 - k * 0.5, ss)

    # 胸前蝴蝶结
    _poly(img, [(210, 470), (178, 454), (174, 488)], LACE, ss)
    _poly(img, [(210, 470), (242, 454), (246, 488)], LACE, ss)
    _poly(img, [(210, 470), (198, 496), (222, 496)], LACE, ss)
    _ell(img, (210, 470), (10, 10), GOLD, ss)

    # 颈链
    _arc(img, hp((210, 388)), (30, 13), GOLD, 2.0, ss, 200, 340)
    _ell(img, hp((210, 399)), (5, 7), GOLD, ss)

    # ---------------- 脸
    _poly(img, [hp(q) for q in _face_outline(head_c[0], head_c[1], RX, RY)], SKIN, ss)
    # 下颌阴影
    _arc(img, hp((head_c[0], head_c[1] + 6)), (RX * 0.66, RY * 0.72), SKIN_SHADOW, 6.0, ss, 30, 150)

    # 腮红
    for bx in (166, 254):
        c = hp((bx, 312))
        l2, m2 = _radial((h, w), (c[0] * ss, c[1] * ss), 30 * ss, BLUSH, p["blush"])
        img = _blend(img, l2, m2)

    # 鼻子
    _ell(img, hp((210, 324)), (4, 3), SKIN_SHADOW, ss)

    # ---------------- 嘴
    mw = 18 * p["mouth_w"]
    curve = p["mouth_curve"]
    mopen = p["mouth_open"]
    mc = hp((210, 350))
    if mopen > 0.06:
        hgt = 4 + 12 * mopen
        pts = []
        for i in range(15):
            k = i / 14
            pts.append((mc[0] - mw + 2 * mw * k, mc[1] - hgt * 0.35 * math.sin(k * math.pi)))
        for i in range(14, -1, -1):
            k = i / 14
            pts.append((mc[0] - mw + 2 * mw * k, mc[1] + hgt * 0.75 * math.sin(k * math.pi)))
        _poly(img, pts, LIP_DARK, ss)
        _ell(img, (mc[0], mc[1] + hgt * 0.42), (mw * 0.5, hgt * 0.28), (120, 118, 220), ss)
    else:
        pts = []
        for i in range(15):
            k = i / 14
            pts.append((mc[0] - mw + 2 * mw * k,
                        mc[1] - curve * 4.5 * math.sin(k * math.pi)))
        _line(img, pts, LIP, 2.4, ss)
        _ell(img, (mc[0], mc[1] + 1.4), (mw * 0.52, 2.4), LIP_DARK, ss)

    # ---------------- 眼（画在脸之后，刘海之前）
    eo = min(p["eye_open"], max(0.02, blink))
    eye_p = dict(p)
    eye_p["eye_open"] = eo
    for side, ex in ((-1, 168), (1, 252)):
        c = hp((ex, 282))
        _eye(img, c[0], c[1], 30, 23, eye_p, side, ss)
        by = 250 - p["brow"] * 7
        pts = []
        for i in range(11):
            k = i / 10
            pts.append((c[0] - 25 + 50 * k,
                        by - 5 * math.sin(k * math.pi) + 2.5 * (k - 0.5) * side))
        _line(img, pts, BROW, 2.0, ss)

    if p["tear"] > 0.05:
        for ex in (162, 258):
            c = hp((ex, 312))
            _ell(img, (c[0], c[1] + 9 * p["tear"]), (3.5, 6 * p["tear"] + 1),
                 (232, 242, 255), ss)

    # ---------------- 两侧垂发（盖住脸的两边）
    for side, sx in ((-1, 118), (1, 302)):
        pts = [hp((sx - side * 16, 168)), hp((sx + side * 22, 200)),
               hp((sx + side * 30, 360)), hp((sx + side * 10, 452)),
               hp((sx - side * 8, 330))]
        _poly(img, pts, HAIR, ss)
        _line(img, [hp((sx - side * 4, 210)), hp((sx + side * 8, 400))], HAIR_LIGHT, 1.8, ss)

    # ---------------- 刘海
    top = 150
    bang = _wavy(248, head_c[0], 92, 6, 7, phase=0.6)
    bang = [hp(q) for q in bang]
    bang = [hp((head_c[0] - 100, top)), hp((head_c[0] + 100, top))] + bang
    _poly(img, bang, HAIR, ss)
    for k in range(5):
        x0 = head_c[0] - 76 + k * 38
        _line(img, [hp((x0, top + 6)), hp((x0 + (k - 2) * 10, 244))], HAIR_LIGHT, 1.8, ss)
    # 刘海在额头上的投影
    _line(img, [hp(q) for q in _wavy(252, head_c[0], 90, 6, 7, phase=0.6)], SKIN_SHADOW, 3.0, ss)

    # ---------------- 发饰
    for side, bx in ((-1, 104), (1, 316)):
        c = hp((bx + side * 24, 148))
        _ell(img, c, (12, 10), LACE, ss)
        _ell(img, (c[0] + side * 17, c[1] + 12), (8, 6), (230, 212, 238), ss)
        _ell(img, (c[0] + side * 9, c[1] + 20), (4.5, 4.5), PEARL, ss)
    # 珍珠发卡（左额）
    for k in range(3):
        _ell(img, hp((150 + k * 14, 208 - k * 3)), (3.2, 3.2), PEARL, ss)

    # 耳环
    for side, sx in ((-1, 132), (1, 288)):
        c = hp((sx + side * 4, 360))
        _line(img, [(c[0], c[1]), (c[0], c[1] + 12)], GOLD, 1.1, ss)
        _ell(img, (c[0], c[1] + 17), (4, 4), PEARL, ss)

    # ---------------- 手
    for side, hx, hy, ang in ((-1, 74, 566, p["arm_l"]), (1, 346, 566, p["arm_r"])):
        c = (hx, hy - ang * 42)
        _ell(img, c, (19, 21), SKIN, ss)
        _ell(img, (c[0], c[1] - 14), (17, 12), SKIN, ss)
        for k in range(3):
            _arc(img, (c[0] + (k - 1) * 9, c[1] - 20), (4.5, 8), SKIN_SHADOW, 1.2, ss, 200, 340)

    # 柔光
    blur = cv2.GaussianBlur(img, (0, 0), 4 * ss)
    img = cv2.addWeighted(img, 0.9, blur, 0.1, 0)

    img = cv2.resize(img, (size, int(size * H / W)), interpolation=cv2.INTER_AREA)
    return img
