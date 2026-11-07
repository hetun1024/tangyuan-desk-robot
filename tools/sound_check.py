#!/usr/bin/env python3
"""声音自检：一步一步试，最后告诉你卡在哪一环。

    python3 tools/sound_check.py

分三段，故意分开，为了定位：
  1. 放一个系统提示音 —— 只测"喇叭通不通"，不碰语音合成
  2. 用系统默认音色说一句 —— 测语音合成
  3. 用你配置里的音色说一句 —— 测你选的音色
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "config.json")
sys.path.insert(0, ROOT)
BEEP = "/System/Library/Sounds/Glass.aiff"


def step(n, title):
    print()
    print("  ── 第 %d 步：%s" % (n, title))


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def main() -> int:
    print()
    print("  ======== 汤圆 · 声音自检 ========")

    # 环境
    step(0, "先看环境")
    vol = run(["osascript", "-e", "output volume of (get volume settings)"]).stdout.strip()
    muted = run(["osascript", "-e", "output muted of (get volume settings)"]).stdout.strip()
    print("     系统音量：%s   静音：%s" % (vol or "?", muted or "?"))
    if muted == "true":
        print("     ✗ 系统是静音的，先去菜单栏把音量打开。")
        return 1
    try:
        v = int(vol)
        if v < 30:
            print("     ⚠️  音量只有 %d，可能听不清。建议调到 50 以上。" % v)
    except (TypeError, ValueError):
        pass

    voice_cfg = "Meijia"
    if os.path.exists(CONFIG):
        try:
            with open(CONFIG, encoding="utf-8") as fh:
                voice_cfg = json.load(fh).get("voice") or "Meijia"
        except Exception:  # noqa: BLE001
            pass
    print("     配置里的音色：%s" % voice_cfg)

    # 1. 提示音
    step(1, "放一个「叮」")
    if os.path.exists(BEEP):
        print("     正在播放……")
        r = run(["afplay", BEEP])
        print("     %s" % ("播放完成（退出码 0）" if r.returncode == 0 else "失败：%s" % r.stderr[:120]))
    else:
        print("     找不到系统提示音，跳过。")

    # 2. 默认音色
    step(2, "用系统默认音色说一句")
    print("     正在说……")
    r = run(["say", "一、二、三，这是系统默认音色的测试。"])
    print("     %s" % ("说完（退出码 0）" if r.returncode == 0 else "失败：%s" % r.stderr[:120]))

    # 3. 你的音色
    step(3, "用配置里的音色（%s）说一句" % voice_cfg)
    online = voice_cfg.endswith("Neural")
    print("     类型：%s" % ("在线（要联网）" if online else "本机"))
    tmp = "/tmp/puffer_voice_probe.out"
    try:
        if online:
            from agent import tts_edge

            tts_edge.synth("你好，我是汤圆，现在用的是这个声音。", voice_cfg, 175, tmp)
        else:
            run(["say", "-v", voice_cfg, "-o", tmp, "你好，我是汤圆，现在用的是这个声音。"])
    except Exception as e:  # noqa: BLE001
        print("     ✗ 合不出来：%s" % str(e)[:120])
        return 1

    dur = 0.0
    info = run(["afinfo", tmp]).stdout
    for line in info.splitlines():
        if "estimated duration" in line:
            try:
                dur = float(line.split(":")[1].split("sec")[0].strip())
            except (IndexError, ValueError):
                pass
            break

    print("     这个音色说中文的时长：%.2f 秒" % dur)
    if dur < 0.6:
        print("     ✗ 等于没声音。这个音色不支持中文（系统不报错，但输出静音）。")
        print("     双击「换音色.command」，换成列表里的 Meijia 或 Tingting。")
        return 1
    print("     正在播放……")
    from agent import voice as voice_mod

    voice_mod.speak("你好，我是汤圆，现在用的是这个声音。", voice_cfg, enabled=True)

    print()
    print("  ======== 怎么判断 ========")
    print("  听到「叮」但没听到说话 → 喇叭没问题，是语音这一层")
    print("  两个都没听到            → 音量 / 输出设备 / 耳机口插着")
    print("  都听到了                → 声音是好的，问题在别处（比如它没真的说出话）")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
