#!/usr/bin/env python3
"""环境自检：一条一条告诉你哪里好了、哪里没装。

    python3 tools/selfcheck.py
"""
from __future__ import annotations

import json
import os
import socket
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

OK, BAD, WARN = "✓", "✗", "!"


def line(mark, text, hint=""):
    print("  %s  %-34s %s" % (mark, text, hint))


def check_python():
    v = sys.version.split()[0]
    line(OK if sys.version_info >= (3, 8) else BAD, "Python %s" % v)


def check_imports():
    for mod, name in [
        ("numpy", "numpy"),
        ("cv2", "opencv（摄像头/画面）"),
        ("sounddevice", "sounddevice（麦克风）"),
        ("vosk", "vosk（备用识别）"),
        ("faster_whisper", "faster-whisper（主识别）"),
        ("edge_tts", "edge-tts（在线音色）"),
    ]:
        try:
            __import__(mod)
            line(OK, name)
        except Exception:  # noqa: BLE001
            mark = WARN if mod in ("vosk", "edge_tts") else BAD
            line(mark, name, "没装")


def check_models():
    whisper = os.path.join(ROOT, "models", "whisper")
    has_w = any(
        os.path.exists(os.path.join(d, "model.bin"))
        for d, _, _ in os.walk(whisper)
    )
    line(OK if has_w else BAD, "whisper 模型", "" if has_w else "还没下载")

    vosk = os.path.join(ROOT, "models", "vosk-model-small-cn-0.22")
    line(OK if os.path.isdir(vosk) else WARN, "vosk 模型", "" if os.path.isdir(vosk) else "没有也不影响")

    yunet = os.path.join(ROOT, "models", "face_detection_yunet_2023mar.onnx")
    line(OK if os.path.exists(yunet) else WARN, "人脸模型", "" if os.path.exists(yunet) else "摄像头功能会缺")


def check_config():
    path = os.path.join(ROOT, "config.json")
    if not os.path.exists(path):
        line(BAD, "config.json", "没有这个文件")
        return
    try:
        cfg = json.load(open(path, encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        line(BAD, "config.json", "格式坏了：%s" % e)
        return
    key = str(cfg.get("api_key", "")).strip()
    line(OK if key else BAD, "对话 API key", "已填" if key else "还没填")
    vkey = str(cfg.get("vision_api_key", "")).strip()
    line(OK if vkey else WARN, "视觉 API key", "已填" if vkey else "没填（看屏幕用不了）")
    line(OK, "音色 %s" % cfg.get("voice", "?"))
    line(OK, "识别 %s" % cfg.get("asr", "?"))
    line(OK, "身体 %s" % cfg.get("body", "?"))


def check_audio():
    try:
        import sounddevice as sd

        # 看的是"系统默认"，不是设备列表里的第一个
        try:
            out_name = sd.query_devices(kind="output")["name"]
        except Exception:  # noqa: BLE001
            out_name = ""
        try:
            in_name = sd.query_devices(kind="input")["name"]
        except Exception:  # noqa: BLE001
            in_name = ""
        line(OK if out_name else BAD, "扬声器（默认）", out_name or "没有")
        line(OK if in_name else BAD, "麦克风（默认）", in_name or "没有")
    except Exception as e:  # noqa: BLE001
        line(BAD, "声卡", str(e)[:40])


def check_face():
    try:
        s = socket.create_connection(("127.0.0.1", 8770), timeout=1)
        s.close()
        line(OK, "表情窗口", "在跑")
    except OSError:
        line(WARN, "表情窗口", "没开（双击「启动表情.command」）")


def check_data():
    d = os.path.join(ROOT, "data")
    if os.path.isdir(d):
        files = sorted(os.listdir(d))
        line(OK, "记忆目录", "、".join(files[:4]) or "空的")
    else:
        line(WARN, "记忆目录", "还没生成（第一次对话后会有）")


def main() -> int:
    print()
    print("  ======== 汤圆 · 环境自检 ========")
    print()
    check_python()
    check_imports()
    print()
    check_models()
    print()
    check_config()
    print()
    check_audio()
    check_face()
    check_data()
    print()
    print("  ✗ = 必须解决   ! = 可以不管   ✓ = 好了")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
