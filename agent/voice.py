"""嘴：把回答念出来。

两级结构，故意的：

  1. 在线音色（Edge）—— 好听，但要联网
  2. 本机 `say`      —— 机械一点，但断网也能说

先试在线，挂了就退回本机。搬到机器人上时，把这两条换成喇叭（aplay / ALSA），
别的代码一行都不用动 —— 这就是为什么语音要单独放一个文件。
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from typing import Optional

from . import tts_edge

LOCAL_FALLBACK = tts_edge.LOCAL_FALLBACK

# 在线音色挂一次就别每次都试了：每句都要等一两秒超时，还会刷屏。
_edge_down = False
_warned = False


# 括号里的动作提示：写给人看的，不该念出来。
# 例：（小声）别闹，说人话。 → 别闹，说人话。
_STAGE = re.compile(r"[（(][^（）()]*[）)]")
_MARK = re.compile(r"[*_`~]+")


def for_speech(text: str) -> str:
    """去掉不该读出来的部分：括号动作、markdown 记号、多余空白。"""
    t = text or ""
    for _ in range(4):  # 嵌套括号多跑几遍
        new = _STAGE.sub("", t)
        if new == t:
            break
        t = new
    t = _MARK.sub("", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = t.strip("，,、 ")
    return t


def available() -> bool:
    return shutil.which("say") is not None


def voices() -> list:
    """系统里有哪些音色（本机）。"""
    if not available():
        return []
    try:
        out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=5).stdout
    except Exception:  # noqa: BLE001
        return []
    found = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        if parts[1].startswith("zh_") or "en_US" in parts[1]:
            found.append(parts[0])
    return found


def _say_local(text: str, voice: Optional[str], rate: int) -> None:
    if not available():
        print("（这台机器没有 say，也没连上在线音色）", file=sys.stderr)
        return
    cmd = ["say"]
    if voice:
        cmd += ["-v", voice]
    if rate:
        cmd += ["-r", str(int(rate))]
    cmd += [text[:400]]
    try:
        subprocess.run(cmd, timeout=60)
    except Exception as e:  # noqa: BLE001
        print("（朗读失败：%s）" % e, file=sys.stderr)


def speak(
    text: str,
    voice: Optional[str] = None,
    enabled: bool = True,
    rate: int = 0,
    pitch: int = 0,
) -> None:
    """念一句话。

    voice 是 "zh-CN-xxxNeural" 这种形状就用在线的，否则用本机的。
    rate 是"每分钟多少词"（150 慢、195 快），0 表示用默认。
    """
    if not enabled or not text:
        return

    text = for_speech(text)
    if not text:
        return  # 整句都是括号里的动作，没什么可念的

    wpm = rate or 175

    global _edge_down, _warned

    if tts_edge.is_edge_voice(voice or "") and not _edge_down:
        try:
            tts_edge.speak(text, voice, wpm, pitch)
            return
        except Exception as e:  # noqa: BLE001
            _edge_down = True
            if not _warned:
                _warned = True
                print(
                    "（在线音色连不上，这段时间都用本机音色。原因：%s）\n"
                    "  想让本机音色好听些：系统设置 → 辅助功能 → 朗读内容 → 系统声音 → "
                    "管理声音 → 中文，下载「美佳」的增强/优质版本。" % str(e)[:60],
                    file=sys.stderr,
                )
            _say_local(text, LOCAL_FALLBACK, wpm)
            return

    _say_local(text, voice, wpm)
