#!/usr/bin/env python3
"""换音色：先列在线的，再列本机的。试听 → 满意 → 自动写进配置。

    python3 tools/voice_picker.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agent import tts_edge, voice  # noqa: E402

CONFIG = os.path.join(ROOT, "config.json")
CACHE = os.path.join(ROOT, "data", "voices.json")
SAMPLE = "你好，我是汤圆。今天过得怎么样？"
MIN_SECONDS = 0.6


# ------------------------------------------------------------ 本机音色
def mac_voices():
    out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
    found = []
    for line in out.splitlines():
        m = re.match(r"^(.+?)\s+([a-z]{2}_[A-Z]{2})\s+#", line)
        if m and m.group(2).startswith("zh"):
            found.append((re.sub(r"\s*\(.*\)$", "", m.group(1)).strip(), m.group(2)))
    return found


def speaks_chinese(name: str) -> bool:
    """本机音色要先验：很多新音色说中文是静音，而且不报错。"""
    tmp = os.path.join("/tmp", "voice_probe.aiff")
    try:
        subprocess.run(["say", "-v", name, "-o", tmp, SAMPLE], capture_output=True, timeout=30)
        info = subprocess.run(["afinfo", tmp], capture_output=True, text=True, timeout=10).stdout
        for line in info.splitlines():
            if "estimated duration" in line:
                return float(line.split(":")[1].split("sec")[0].strip()) >= MIN_SECONDS
    except Exception:  # noqa: BLE001
        return False
    return False


def load_cache():
    try:
        with open(CACHE, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return {}


def save_cache(d):
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False)


def local_usable():
    cache = load_cache()
    out = []
    dirty = False
    for name, loc in mac_voices():
        key = "%s|%s" % (name, loc)
        if key not in cache:
            cache[key] = speaks_chinese(name)
            dirty = True
        if cache[key]:
            out.append((name, loc))
    if dirty:
        save_cache(cache)
    return out


# ---------------------------------------------------------------- 主流程
def current() -> tuple:
    try:
        with open(CONFIG, encoding="utf-8") as fh:
            cfg = json.load(fh)
        return cfg.get("voice", ""), int(cfg.get("pitch") or 0)
    except Exception:  # noqa: BLE001
        return "", 0


def save_voice(name: str, pitch: int = 0) -> bool:
    try:
        with open(CONFIG, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except Exception:  # noqa: BLE001
        cfg = {}
    cfg["voice"] = name
    cfg["pitch"] = int(pitch)
    with open(CONFIG, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)
    return True


def main() -> int:
    cur_voice, cur_pitch = current()
    entries = []  # (voice_id, label, pitch)

    def show(title, items, note=""):
        if not items:
            return
        print()
        print("  ── %s ──" % title)
        if note:
            print("     %s" % note)
        for vid, label, pitch in items:
            entries.append((vid, pitch))
            star = " ★" if (vid == cur_voice and pitch == cur_pitch) else ""
            print("  %2d  %-30s%s" % (len(entries), label, star))

    # 顺序很重要：先给"一定能用"的，最后才是"要联网、可能连不上"的
    show("离线神经语音（断网也能用，最稳）",
         [(k, "华言 · 离线女声", 0) for k in voice.piper_voices()])
    show("本机音色（不联网，机械一点）",
         [(n, "%s · 本机" % n, 0) for n, _loc in local_usable()])
    show("在线音色（要联网，现在经常连不上）",
         [(v, l, p) for v, l, p in tts_edge.EDGE_VOICES],
         note="这些更好听，但网络被拦的时候一句都出不来。")
    show("在线·萌系（把音高抬高）",
         [(v, l, p) for v, l, p in tts_edge.CUTE_VOICES],
         note="同样需要网络。")

    print()
    print("  输入编号试听，q 退出")

    while True:
        try:
            pick = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if pick.lower() in ("q", "quit", "退出"):
            return 0
        if not pick.isdigit():
            continue

        idx = int(pick) - 1
        if not (0 <= idx < len(entries)):
            print("  没有这个编号。")
            continue

        name, pitch = entries[idx]
        online = tts_edge.is_edge_voice(name)
        kind = "在线" if online else ("离线" if name.startswith("piper:") else "本机")
        print("  ▶ %s  %s（%s）" % (name, ("+%dHz" % pitch) if pitch else "", kind))

        try:
            voice.speak(SAMPLE, name, enabled=True, pitch=pitch)
        except Exception as e:  # noqa: BLE001
            print("  ✗ 播不出来：%s" % str(e)[:120])
            print("    在线音色连不上就检查网络；本机音色就换一个。")
            continue

        ans = input("  用它吗？（y 确定 / 回车听下一个）：").strip().lower()
        if ans == "y":
            save_voice(name, pitch)
            print("  ✓ 换好了：%s %s" % (name, ("+%dHz" % pitch) if pitch else ""))
            print("    下次双击「启动大脑.command」就生效。")
            voice.speak("好，以后我就用这个声音了。", name, enabled=True, pitch=pitch)
            return 0


if __name__ == "__main__":
    sys.exit(main())
