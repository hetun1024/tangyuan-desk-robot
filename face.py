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

from agent import live2d

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


STATES = list(live2d.MOODS)
ORDER = STATES  # 键盘 1-9 / 空格 轮播用的顺序

CONVERSATION = {"idle", "listening", "thinking", "talking"}

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
    """当前表情 + 过渡。

    旧的 14 套参数化抽象表情已经删掉了 —— 现在她的脸来自立绘，
    情绪只是"换哪张图"，过渡交给 Model 里的混合。
    """

    def __init__(self, name: str = "idle"):
        self.model = live2d.Model()
        self.name = name if name in live2d.MOODS else "idle"
        self.prev = None      # 上一张图，用来做淡入
        self.t0 = 0.0
        self.dur = 0.0
        self._was_conv = self.name in CONVERSATION

    def set(self, name: str, now: float):
        if name not in live2d.MOODS or name == self.name:
            return
        self.prev = self.model.frames.get(live2d.MOODS.get(self.name, "idle"))
        self.name = name
        quick = (name in CONVERSATION) and self._was_conv
        self.dur = FAST if quick else SLOW
        self._was_conv = name in CONVERSATION
        self.t0 = now

    def current(self, now: float):
        """返回 {当前状态, 过渡进度}。"""
        if self.dur <= 0:
            return {"mood": self.name, "k": 1.0}
        k = (now - self.t0) / self.dur
        if k >= 1.0:
            self.dur = 0.0
            return {"mood": self.name, "k": 1.0}
        return {"mood": self.name, "k": ease(min(1.0, k))}

    def render(self, size: int, now: float, t: float, blink: float):
        cur = self.current(now)
        talk = 0.0
        if self.name == "talking":
            talk = 0.35 + 0.65 * abs(math.sin(t * 7.0))
        b = 0.0 if blink >= 0.5 else 1.0
        if blink > 0.1 and blink < 0.9:
            b = 1.0 - blink
        img = self.model.frame(cur["mood"], t=t, blink=b, talk=talk,
                               fade=self.prev)
        if img.shape[0] != size:
            img = cv2.resize(img, (size, size), interpolation=cv2.INTER_AREA)
        return img


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
    ap.add_argument("--size", type=int, default=640)
    ap.add_argument("--fullscreen", action="store_true")
    args = ap.parse_args()

    if args.shot:
        shot_model = live2d.Model()
        tile = args.size // 2
        cols = 4
        rows = (len(ORDER) + cols - 1) // cols
        sheet = np.full((rows * tile, cols * tile, 3), 12, np.uint8)
        for i, name in enumerate(ORDER):
            im = shot_model.frame(name, t=0.9)
            im = cv2.resize(im, (tile, tile), interpolation=cv2.INTER_AREA)
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
