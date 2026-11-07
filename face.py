#!/usr/bin/env python3
"""脸：参数驱动的发光小生物。

为什么是"参数"而不是"十几个 if 分支"：
表情之间的过渡要连续，就必须能对两组数字做加权平均。字符串（"round"/"heart"）
没法插值，只有数字可以。

所以每个表情是一组数：

    eye_w, eye_h      眼睛多大
    eye_gap, eye_cy   眼睛在哪
    top, bot          上下渐变色
    blush             腮红强度
    mouth             嘴的形状（离散，靠"眯一下"遮住切换）
    prop, prop_a      道具和它的透明度

过渡规则：
  * 数字 → 直接插值（颜色、大小、位置、腮红、道具透明度都连续变）
  * 形状 → 在中点切换，同时把眼睛缩到 0.35 倍，遮住突变

    python3 face.py                       # 开窗口
    python3 face.py --shot out/faces.png  # 14 个表情拼一张图
    python3 face.py --emotion happy       # 固定一个

大脑改表情：curl "http://127.0.0.1:8770/emotion?name=happy"
"""
from __future__ import annotations

import argparse
import math
import os
import random
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import cv2
import numpy as np

BG = (10, 9, 12)
BLUE_TOP = (255, 216, 170)  # BGR #aad8ff
BLUE_BOT = (250, 140, 125)  # BGR #7d8cfa
GRAY_TOP = (200, 196, 190)
GRAY_BOT = (150, 145, 165)
WARM_TOP = (215, 225, 255)
WARM_BOT = (215, 170, 250)
BLUSH_C = (150, 130, 255)
WHITE = (250, 250, 255)
GOLD = (90, 210, 255)
PINK = (150, 110, 250)
MUTED = (200, 205, 220)
PORT = 8770

BLINK_MIN, BLINK_MAX, BLINK_CLOSED, BLINK_DOUBLE = 1.2, 2.6, 0.10, 0.18
FAST = 0.12  # 对话状态之间切换
SLOW = 0.26  # 情绪变化


def _p(**kw):
    base = dict(
        shape="round", eye_w=0.19, eye_h=0.25, eye_gap=0.145, eye_cy=0.47,
        top=BLUE_TOP, bot=BLUE_BOT, blush=0.18,
        mouth="dot", prop=None, prop_a=1.0, eye_scale=1.0,
    )
    base.update(kw)
    return base


PRESETS = {
    "idle": _p(),
    "listening": _p(eye_w=0.213, eye_h=0.28, blush=0.22),
    "thinking": _p(blush=0.12, prop="dots"),
    "talking": _p(blush=0.24, mouth="talk"),
    "happy": _p(shape="arc", mouth="smile", blush=0.55, top=WARM_TOP, bot=WARM_BOT),
    "love": _p(shape="heart", mouth="small", blush=0.75, top=(190, 190, 255), bot=(190, 120, 240)),
    "sleepy": _p(shape="arc_down", mouth="line", prop="zzz", blush=0.25, top=GRAY_TOP, bot=GRAY_BOT),
    "surprised": _p(eye_w=0.213, eye_h=0.28, mouth="o", prop="sweat", blush=0.30),
    "angry": _p(shape="bar", mouth="dot", blush=0.10, top=(210, 200, 200), bot=(150, 120, 175)),
    "star": _p(shape="star", mouth="dot", prop="sparkle", blush=0.20,
               top=(150, 235, 255), bot=(60, 190, 240)),
    "question": _p(mouth="dot", prop="question", blush=0.20),
    "coffee": _p(shape="arc", mouth="dot", prop="coffee", blush=0.50),
    "eating": _p(eye_w=0.213, eye_h=0.28, mouth="chew", prop="food", blush=0.40),
    "sad": _p(mouth="frown", blush=0.35, top=GRAY_TOP, bot=(180, 150, 200)),
}
ORDER = list(PRESETS)
CONVERSATION = {"idle", "listening", "thinking", "talking"}


# ---------------------------------------------------------------- 基础合成
def squircle(w, h, n: float = 3.2) -> np.ndarray:
    w, h = max(2, int(w)), max(2, int(h))
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    nx = (xx - (w - 1) / 2.0) / ((w - 1) / 2.0)
    ny = (yy - (h - 1) / 2.0) / ((h - 1) / 2.0)
    d = np.abs(nx) ** n + np.abs(ny) ** n
    return np.clip((1.0 - d) * 60.0, 0.0, 1.0)


def composite(canvas, x, y, rgb, a):
    x, y = int(x), int(y)
    h, w = a.shape
    H, W = canvas.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + w), min(H, y + h)
    if x1 <= x0 or y1 <= y0:
        return
    pa = a[y0 - y : y1 - y, x0 - x : x1 - x][..., None]
    prgb = rgb[y0 - y : y1 - y, x0 - x : x1 - x]
    dst = canvas[y0:y1, x0:x1].astype(np.float32)
    canvas[y0:y1, x0:x1] = np.clip(dst * (1 - pa) + prgb, 0, 255).astype(np.uint8)


def add_glow(canvas, x, y, a, color, strength=0.35):
    x, y = int(x), int(y)
    h, w = a.shape
    pad = int(max(h, w) * 0.9) + 4
    big = np.zeros((h + pad * 2, w + pad * 2), np.float32)
    big[pad : pad + h, pad : pad + w] = a
    big = cv2.GaussianBlur(big, (0, 0), sigmaX=max(2.0, max(h, w) * 0.18))
    H, W = canvas.shape[:2]
    x0, y0 = x - pad, y - pad
    bx0, by0 = max(0, -x0), max(0, -y0)
    bx1, by1 = min(big.shape[1], W - x0), min(big.shape[0], H - y0)
    if bx1 <= bx0 or by1 <= by0:
        return
    region = canvas[y0 + by0 : y0 + by1, x0 + bx0 : x0 + bx1].astype(np.float32)
    g = big[by0:by1, bx0:bx1, None] * strength
    canvas[y0 + by0 : y0 + by1, x0 + bx0 : x0 + bx1] = np.clip(
        region + np.array(color, np.float32) * g, 0, 255
    ).astype(np.uint8)


def tint(alpha, color):
    return alpha[..., None] * np.array(color, np.float32)


# ------------------------------------------------------------------ 零件
def eye_patch(w, h, top, bot, squash=1.0):
    w, h = max(3, int(w)), max(3, int(h))
    a = squircle(w, h)
    if squash != 1.0:
        nh = max(2, int(h * squash))
        a = cv2.resize(a, (w, nh), interpolation=cv2.INTER_AREA)
        h = nh
    t = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None]
    rgb = np.zeros((h, w, 3), np.float32)
    for c in range(3):
        rgb[:, :, c] = top[c] * (1 - t) + bot[c] * t
    rgb = rgb * a[..., None]

    yy, xx = np.mgrid[0:h, 0:w]
    hw, hh = max(1.5, w * 0.19), max(1.5, h * 0.17)
    d = ((xx - w * 0.34) / hw) ** 2 + ((yy - h * 0.30) / hh) ** 2
    dot = np.clip((1 - d) * 2.4, 0, 1) * 0.85
    rgb = np.clip(rgb + dot[..., None] * 255, 0, 255) * a[..., None]
    return rgb, a


def heart_patch(w, h, color=PINK):
    w, h = max(6, int(w)), max(6, int(h))
    m = np.zeros((h, w), np.uint8)
    r = w * 0.26
    for cx in (w * 0.30, w * 0.70):
        cv2.circle(m, (int(cx), int(h * 0.34)), int(r), 255, -1)
    cv2.fillPoly(m, [np.array([[w * .05, h * .36], [w * .95, h * .36], [w * .50, h * .97]],
                              np.int32)], 255)
    a = cv2.GaussianBlur(m, (0, 0), sigmaX=max(1.0, w * 0.02)).astype(np.float32) / 255.0
    return tint(a, color), a


def star_patch(w, h, color=GOLD, points=5, inner=0.45):
    w, h = max(6, int(w)), max(6, int(h))
    m = np.zeros((h, w), np.uint8)
    cx, cy, R = w / 2.0, h / 2.0, min(w, h) * 0.48
    pts = []
    for i in range(points * 2):
        ang = -math.pi / 2 + i * math.pi / points
        r = R if i % 2 == 0 else R * inner
        pts.append([cx + r * math.cos(ang), cy + r * math.sin(ang)])
    cv2.fillPoly(m, [np.array(pts, np.int32)], 255)
    a = cv2.GaussianBlur(m, (0, 0), sigmaX=max(1.0, w * 0.02)).astype(np.float32) / 255.0
    return tint(a, color), a


def text_patch(text, scale, color=WHITE, thick=3):
    (tw, th), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_DUPLEX, scale, thick)
    m = np.zeros((th + base + 14, tw + 14), np.uint8)
    cv2.putText(m, text, (7, th + 7), cv2.FONT_HERSHEY_DUPLEX, scale, 255, thick, cv2.LINE_AA)
    a = cv2.GaussianBlur(m, (0, 0), sigmaX=1.1).astype(np.float32) / 255.0
    return tint(a, color), a


# ------------------------------------------------------------------ 道具
def draw_prop(img, kind, cx, cy, s, t, alpha=1.0):
    if not kind or alpha <= 0.01:
        return

    def put(x, y, rgb, a):
        composite(img, x, y, rgb * alpha, a * alpha)

    if kind == "zzz":
        for i in range(3):
            rgb, a = text_patch("Z", 0.24 + i * 0.10, WHITE, 3)
            bob = math.sin(t * 1.8 + i) * s * 0.01
            x, y = int(cx + s * 0.16 + i * s * 0.07), int(cy - s * 0.20 - i * s * 0.09 + bob)
            add_glow(img, x, y, a, WHITE, 0.12 * alpha)
            put(x, y, rgb, a)

    elif kind == "sparkle":
        for i, (dx, dy, k) in enumerate(((0.33, -0.30, 1.0), (0.44, -0.06, 0.55))):
            tw = 0.55 + 0.45 * math.sin(t * 3.2 + i * 2)
            rgb, a = star_patch(s * 0.11 * k, s * 0.11 * k, GOLD, points=4, inner=0.30)
            x, y = int(cx + s * dx), int(cy + s * dy)
            add_glow(img, x, y, a, GOLD, 0.25 * tw * alpha)
            put(x, y, rgb * tw, a * tw)

    elif kind == "sweat":
        bob = math.sin(t * 2.0) * s * 0.008
        rgb, a = text_patch("!", s / 95.0, BLUE_TOP, 4)
        x, y = int(cx + s * 0.31), int(cy - s * 0.32 + bob)
        add_glow(img, x, y, a, BLUE_TOP, 0.14 * alpha)
        put(x, y, rgb, a)

    elif kind == "question":
        bob = math.sin(t * 2.2) * s * 0.008
        rgb, a = text_patch("?", s / 85.0, (210, 195, 255), 4)
        x, y = int(cx + s * 0.28), int(cy - s * 0.33 + bob)
        add_glow(img, x, y, a, (210, 195, 255), 0.16 * alpha)
        put(x, y, rgb, a)

    elif kind == "dots":
        for i in range(3):
            k = 0.5 + 0.5 * math.sin(t * 4.0 - i * 0.9)
            a = squircle(s * 0.030, s * 0.030, 2.0)
            rgb = tint(a, (180, 190, 230))
            x, y = int(cx + s * 0.16 + i * s * 0.055), int(cy + s * 0.16)
            put(x, y, rgb, a * (0.35 + 0.65 * k))

    elif kind == "coffee":
        w, h = int(s * 0.15), int(s * 0.115)
        x, y = int(cx - w / 2 - s * 0.06), int(cy + s * 0.17)
        m = np.zeros((h + 12, w + 12), np.uint8)
        cv2.rectangle(m, (4, 14), (w - 6, h + 6), 255, -1)
        cv2.ellipse(m, (int(w * 0.22), 14), (int(w * 0.24), 5), 0, 0, 360, 255, -1)
        cv2.circle(m, (w + 2, 14 + h // 2), 8, 255, 4)
        a = cv2.GaussianBlur(m, (0, 0), 1.0).astype(np.float32) / 255.0
        add_glow(img, x, y, a, WHITE, 0.10 * alpha)
        put(x, y, tint(a, (230, 228, 240)), a)
        for i in range(2):
            sx = x + int(w * (0.34 + 0.32 * i))
            for k in range(3):
                yy = y + 4 - k * 7
                cv2.circle(img, (sx + int(math.sin(t * 2 + k + i) * 2), yy), 2, (110, 110, 130), -1)

    elif kind == "food":
        a = squircle(s * 0.13, s * 0.075, 2.3)
        x, y = int(cx + s * 0.20), int(cy + s * 0.21)
        add_glow(img, x, y, a, (210, 195, 250), 0.12 * alpha)
        put(x, y, tint(a, (210, 195, 250)), a)


# ------------------------------------------------------------------ 画脸
def draw_face(size, p, t, blink=1.0):
    img = np.full((size, size, 3), BG, np.uint8)

    ew = size * p["eye_w"] * p["eye_scale"]
    eh = size * p["eye_h"] * p["eye_scale"]
    gap = size * p["eye_gap"]

    # 呼吸：整个脸的起伏。没有舵机也能有"在动"的感觉 ——
    # 幅度很小（0.6% 画布），看久了会觉得它在喘气。
    breathe = math.sin(t * 0.85) * size * 0.006
    sway = math.sin(t * 0.31) * size * 0.004
    cx = int(size) // 2 + int(sway)
    cy = int(size * p["eye_cy"] + breathe)
    style = p["shape"]
    top, bot = p["top"], p["bot"]

    for side in (-1, 1):
        ex = int(cx + side * gap - ew / 2)

        if style == "round":
            h = max(2, int(eh * blink))
            rgb, a = eye_patch(ew, h, top, bot)
            add_glow(img, ex, cy - h // 2, a, bot, 0.30)
            composite(img, ex, cy - h // 2, rgb, a)

        elif style in ("arc", "arc_down"):
            if blink < 0.5:
                cv2.line(img, (ex + int(ew * 0.12), cy + 4),
                         (ex + int(ew * 0.88), cy + 4), WHITE, 6, cv2.LINE_AA)
            elif style == "arc":
                cv2.ellipse(img, (int(ex + ew / 2), cy + int(eh * 0.12)),
                            (int(ew / 2), int(eh / 2)), 0, 200, 340, WHITE, 7, cv2.LINE_AA)
            else:
                cv2.ellipse(img, (int(ex + ew / 2), cy - int(eh * 0.10)),
                            (int(ew / 2), int(eh / 2)), 0, 20, 160, WHITE, 6, cv2.LINE_AA)

        elif style == "heart":
            h2 = max(2.0, eh * 0.95 * blink)
            rgb, a = heart_patch(ew * 0.95, h2, tuple(bot))
            add_glow(img, ex, cy - int(h2 / 2), a, bot, 0.40)
            composite(img, ex, cy - int(h2 / 2), rgb, a)

        elif style == "star":
            h2 = max(2.0, eh * 0.95 * blink)
            rgb, a = star_patch(ew * 1.0, h2, GOLD)
            add_glow(img, ex, cy - int(h2 / 2), a, GOLD, 0.45)
            composite(img, ex, cy - int(h2 / 2), rgb, a)

        elif style == "bar":
            h2 = max(2.0, eh * blink)
            a = squircle(ew * 0.30, h2, 7.0)
            rgb = tint(a, top)
            add_glow(img, ex + int(ew * 0.35), cy - int(h2 / 2), a, bot, 0.28)
            composite(img, ex + int(ew * 0.35), cy - int(h2 / 2), rgb, a)

    if p["blush"] > 0:
        bw, bh = int(size * 0.08), int(size * 0.045)
        a = squircle(bw, bh, 2.0)
        rgb = tint(a, BLUSH_C)
        for side in (-1, 1):
            x = int(cx + side * gap * 1.45 - bw // 2)
            y = cy + int(size * 0.075)
            composite(img, x, y, rgb, a * p["blush"] * 0.5)

    my = cy + int(size * 0.125)
    m = p["mouth"]
    if m == "dot":
        cv2.ellipse(img, (cx, my + 12), (int(size * .026), int(size * .017)), 0, 0, 360, MUTED, -1, cv2.LINE_AA)
    elif m == "smile":
        cv2.ellipse(img, (cx, my + 2), (int(size * .055), int(size * .042)), 0, 8, 172, WHITE, 5, cv2.LINE_AA)
    elif m == "frown":
        cv2.ellipse(img, (cx, my + 14), (int(size * .050), int(size * .034)), 0, 188, 352, WHITE, 5, cv2.LINE_AA)
    elif m == "line":
        cv2.line(img, (cx - int(size * .028), my + 4), (cx + int(size * .028), my + 4), WHITE, 4, cv2.LINE_AA)
    elif m == "o":
        cv2.circle(img, (cx, my + 4), int(size * .025), WHITE, 4, cv2.LINE_AA)
    elif m == "small":
        cv2.ellipse(img, (cx, my + 2), (int(size * .026), int(size * .017)), 0, 0, 360, PINK, -1, cv2.LINE_AA)
    elif m == "talk":
        h = int(size * (0.010 + 0.030 * (0.5 + 0.5 * math.sin(t * 13.0))))
        cv2.ellipse(img, (cx, my + 6), (int(size * .031), h), 0, 0, 360, WHITE, -1, cv2.LINE_AA)
    elif m == "chew":
        h = int(size * (0.015 + 0.010 * math.sin(t * 9.0)))
        cv2.ellipse(img, (cx, my + 6), (int(size * .038), h), 0, 0, 360, WHITE, -1, cv2.LINE_AA)

    draw_prop(img, p["prop"], cx, cy, size, t, p["prop_a"])
    return img


# ------------------------------------------------------------------ 过渡
def ease(k: float) -> float:
    k = max(0.0, min(1.0, k))
    return k * k * (3 - 2 * k)


def blend(a, b, k):
    """两组参数按 k 混合：数字插值，离散量在中点切换。"""
    out = {}
    shape_change = a["shape"] != b["shape"] or a["mouth"] != b["mouth"]
    for key in a:
        va, vb = a[key], b[key]
        if isinstance(va, bool) or isinstance(vb, bool):
            out[key] = va if k < 0.5 else vb
        elif isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            out[key] = va * (1 - k) + vb * k
        elif isinstance(va, tuple) and isinstance(vb, tuple):
            # 颜色：形状要变的时候直接在中点换色，不做插值。
            # 蓝→金插到一半是灰的，很难看；眯眼那一下足够遮住突变。
            if shape_change:
                out[key] = va if k < 0.5 else vb
            else:
                out[key] = tuple(x * (1 - k) + y * k for x, y in zip(va, vb))
        else:
            out[key] = va if k < 0.5 else vb
    if shape_change:
        # 形状要突变的地方把眼睛缩一下 —— 像"眯一下再换"，比硬切自然
        out["eye_scale"] = out["eye_scale"] * (1.0 - 0.50 * math.sin(math.pi * k))
    return out


class Face:
    """当前表情 + 过渡状态。"""

    def __init__(self, name: str = "idle"):
        self.name = name if name in PRESETS else "idle"
        self.frm = dict(PRESETS[self.name])
        self.to = dict(PRESETS[self.name])
        self.t0 = 0.0
        self.dur = 0.0
        self._was_conv = self.name in CONVERSATION

    def set(self, name: str, now: float):
        if name not in PRESETS or name == self.name:
            return
        self.frm = dict(self.current(now))
        self.name = name
        self.to = dict(PRESETS[name])
        quick = (name in CONVERSATION) and self._was_conv
        self.dur = FAST if quick else SLOW
        self._was_conv = name in CONVERSATION
        self.t0 = now

    def current(self, now: float):
        if self.dur <= 0:
            return self.to
        k = (now - self.t0) / self.dur
        if k >= 1.0:
            self.dur = 0.0
            return self.to
        return blend(self.frm, self.to, ease(k))

    def render(self, size: int, now: float, t: float, blink: float):
        return draw_face(size, self.current(now), t, blink)


# ------------------------------------------------------------------ 眨眼
class Blinker:
    def __init__(self, seed=None):
        self.rng = random.Random(seed)
        self.events = []

    def _schedule(self, start):
        gap = self.rng.uniform(BLINK_MIN, BLINK_MAX)
        s0 = start + gap
        self.events.append((s0, s0 + BLINK_CLOSED))
        if self.rng.random() < BLINK_DOUBLE:
            s1 = s0 + BLINK_CLOSED + self.rng.uniform(0.12, 0.22)
            self.events.append((s1, s1 + BLINK_CLOSED))

    def at(self, t):
        self.events = [e for e in self.events if e[1] > t - 10]
        guard = 0
        while (not self.events or self.events[-1][0] < t + 8) and guard < 200:
            self._schedule(self.events[-1][0] if self.events else t)
            guard += 1
        for a, b in self.events:
            if a <= t <= b:
                return 0.08
        return 1.0


# ------------------------------------------------------------------ 服务
class State:
    def __init__(self):
        self.face = Face("idle")


def serve(st: State):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path == "/emotion":
                st.face.set((q.get("name") or ["idle"])[0], time.time())
                body = ("ok " + st.face.name).encode()
            elif u.path == "/look":
                body = b"ok"
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", PORT), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--emotion", default=None)
    ap.add_argument("--shot", default=None)
    ap.add_argument("--size", type=int, default=512)
    ap.add_argument("--fullscreen", action="store_true")
    args = ap.parse_args()

    if args.shot:
        tile = args.size // 2
        cols = 4
        rows = (len(ORDER) + cols - 1) // cols
        sheet = np.full((rows * tile, cols * tile, 3), 12, np.uint8)
        for i, name in enumerate(ORDER):
            im = draw_face(tile, dict(PRESETS[name]), 0.9)
            cv2.putText(im, name, (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                        (110, 110, 120), 1, cv2.LINE_AA)
            r, c = divmod(i, cols)
            sheet[r * tile : (r + 1) * tile, c * tile : (c + 1) * tile] = im
        os.makedirs(os.path.dirname(os.path.abspath(args.shot)) or ".", exist_ok=True)
        cv2.imwrite(args.shot, sheet)
        print("写好", args.shot)
        return 0

    st = State()
    if args.emotion:
        st.face = Face(args.emotion)
    try:
        srv = serve(st)
    except OSError:
        print("已经有一个表情窗口在跑了（端口 %d 被占）。" % PORT)
        print("看不到它的话：按 F3 打开调度中心，或关掉旧的那个再来。")
        return 0

    win = "tangyuan"
    if args.fullscreen:
        cv2.namedWindow(win, cv2.WND_PROP_FULLSCREEN)
        cv2.setWindowProperty(win, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    else:
        cv2.namedWindow(win, cv2.WINDOW_NORMAL)

    # 默认置顶：不置顶的话窗口开出来会被终端和浏览器盖住，看着就像"没弹出来"
    topmost = True

    def apply_topmost(on: bool):
        try:
            cv2.setWindowProperty(win, cv2.WND_PROP_TOPMOST, 1 if on else 0)
        except Exception:  # noqa: BLE001
            pass

    # 固定到左上角：位置每次都一样，你才知道往哪看
    try:
        cv2.moveWindow(win, 40, 60)
    except Exception:  # noqa: BLE001
        pass
    apply_topmost(True)

    print("表情服务 http://127.0.0.1:%d/emotion?name=happy" % PORT)
    print("  空格/n 下一个   p 上一个   1-9 跳转   a 轮播   t 置顶开关   q 退出")
    print()
    blinker = Blinker()
    t0 = time.time()
    auto = False
    last_auto = 0.0
    idx = ORDER.index(st.face.name)
    last_shown = None
    try:
        while True:
            now = time.time()
            t = now - t0
            if auto and now - last_auto > 1.2:
                idx = (idx + 1) % len(ORDER)
                st.face.set(ORDER[idx], now)
                last_auto = now

            if st.face.name != last_shown:
                last_shown = st.face.name
                print("  → %s" % last_shown)

            cv2.imshow(win, st.face.render(args.size, now, t, blinker.at(t)))
            k = cv2.waitKey(16) & 0xFF
            if k == ord("q"):
                break
            elif k in (ord(" "), ord("n")):
                idx = (idx + 1) % len(ORDER)
                st.face.set(ORDER[idx], now)
                auto = False
            elif k == ord("p"):
                idx = (idx - 1) % len(ORDER)
                st.face.set(ORDER[idx], now)
                auto = False
            elif k == ord("a"):
                auto = not auto
                last_auto = 0.0
            elif k == ord("t"):
                topmost = not topmost
                apply_topmost(topmost)
                print("  置顶：%s" % ("开" if topmost else "关"))
            elif ord("1") <= k <= ord("9"):
                idx = min(k - ord("1"), len(ORDER) - 1)
                st.face.set(ORDER[idx], now)
                auto = False
    finally:
        srv.shutdown()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
