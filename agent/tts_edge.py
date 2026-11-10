"""在线音色：微软 Edge 的语音接口。

为什么加这一层：macOS 自带的中文音色只有三个能出声，而且都是十年前的风格。
Edge 的音色是真人录制的神经网络模型，免费、不用注册、不用 key，中文有 8 个。

代价是**要联网**。所以这里不删掉原来的 `say`，而是做成一前一后：
先试在线，失败就退回本机 —— 断网了它还能说话，只是声音变回机械的。
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile

# 常用中文音色。描述是从实际听感写的，不是官方宣传语。
# (音色 id, 说明, 音高偏移 Hz)
EDGE_VOICES = [
    ("zh-CN-XiaoxiaoNeural", "晓晓 · 女 · 自然亲切（默认）", 0),
    ("zh-CN-XiaoyiNeural", "晓伊 · 女 · 年轻活泼", 0),
    ("zh-CN-YunxiNeural", "云希 · 男 · 年轻温和", 0),
    ("zh-CN-YunyangNeural", "云扬 · 男 · 播音腔，端正", 0),
    ("zh-CN-YunjianNeural", "云健 · 男 · 低沉有力", 0),
    ("zh-CN-YunxiaNeural", "云夏 · 男 · 少年感", 0),
    ("zh-CN-liaoning-XiaobeiNeural", "晓北 · 女 · 东北话", 0),
    ("zh-CN-shaanxi-XiaoniNeural", "晓妮 · 女 · 陕西话", 0),
]

# 萌系：没有现成的萝莉音，就把年轻女声的音高抬上去。
# 40Hz 大约是 2 个半音，还在"甜"的范围；65Hz 开始有点过头了。
CUTE_VOICES = [
    ("zh-CN-XiaoyiNeural", "晓伊 +40Hz · 甜妹", 40),
    ("zh-CN-XiaoyiNeural", "晓伊 +65Hz · 更幼（可能过头）", 65),
    ("zh-CN-XiaoxiaoNeural", "晓晓 +40Hz · 软糯", 40),
    ("zh-TW-HsiaoYuNeural", "曉雨 +30Hz · 台湾腔软萌", 30),
    ("zh-TW-HsiaoChenNeural", "曉臻 +25Hz · 台湾腔温柔", 25),
]

LOCAL_FALLBACK = "Meijia"


def available() -> bool:
    try:
        import edge_tts  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def is_edge_voice(voice: str) -> bool:
    return bool(voice) and voice.endswith("Neural") and "-" in voice


def _pct(rate_wpm: int) -> str:
    """把"每分钟多少词"换算成 Edge 要的百分比。175 是正常语速。"""
    pct = int(round((rate_wpm - 175) / 175.0 * 100))
    return "%+d%%" % max(-30, min(30, pct))


def synth(
    text: str, voice: str, rate_wpm: int = 175, pitch: int = 0, out: str | None = None
) -> str:
    """合成一段 mp3，返回路径。pitch 是音高偏移（Hz），0 表示原声。"""
    import edge_tts

    path = out or os.path.join(tempfile.gettempdir(), "puffer_tts.mp3")
    kwargs = {"rate": _pct(rate_wpm)}
    if pitch:
        kwargs["pitch"] = "%+dHz" % int(pitch)
    last = None
    for attempt in range(2):          # 网络是抽的，失败一次再试一次
        try:
            communicate = edge_tts.Communicate(text[:600], voice, **kwargs)
            asyncio.run(communicate.save(path))
            return path
        except Exception as e:  # noqa: BLE001
            last = e
            if attempt == 0:
                import time as _t

                _t.sleep(0.4)
    raise last


def speak(text: str, voice: str, rate_wpm: int = 175, pitch: int = 0) -> None:
    path = synth(text, voice, rate_wpm, pitch)
    subprocess.run(["afplay", path], timeout=120)


if __name__ == "__main__":
    import sys

    v = sys.argv[1] if len(sys.argv) > 1 else EDGE_VOICES[0][0]
    t = sys.argv[2] if len(sys.argv) > 2 else "你好，我是汤圆。"
    print("合成中：%s" % v)
    speak(t, v)
    print("完成")
