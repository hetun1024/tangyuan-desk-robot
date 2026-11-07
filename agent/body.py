"""身体：把"说、听、看、表情"从具体硬件上剥出来。

为什么要这一层：今天汤圆用的是 Mac 的扬声器和麦克风；过两周要换成一个
ESP32 + 喇叭 + 麦克风阵列的球。如果代码里到处直接调 `say` 和 `sounddevice`，
换硬件就得改十几个地方。

定义成四个动作之后：
  * MacBody  —— 现在这套（系统扬声器 / 麦克风 / 摄像头）
  * NetBody  —— 连一个局域网地址；ESP32 那头只要实现四个 HTTP 接口

换硬件 = 在 config.json 里把 body 从 "mac" 改成 "net"，填个 IP。
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from typing import Dict, Optional


class BodyError(RuntimeError):
    pass


class Body:
    """身体该有的四个动作。谁实现都行，上层不关心是 Mac 还是一块板子。"""

    name = "base"

    def speak(self, text: str, rate: int = 175, pitch: int = 0) -> None:
        raise NotImplementedError

    def listen(self) -> str:
        raise NotImplementedError

    def look(self) -> Dict:
        raise NotImplementedError

    def face(self, emotion: str) -> None:
        """表情。Mac 上就是什么都不做。"""
        return None

    def close(self) -> None:
        return None


class MacBody(Body):
    """现在用的身体：Mac 自带的扬声器、麦克风、摄像头。"""

    name = "mac"

    def __init__(self, cfg):
        self.cfg = cfg
        self._ears = None

    def _ensure_ears(self):
        if self._ears is None:
            from . import ears as ears_mod

            self._ears = ears_mod.Ears(backend=self.cfg.asr, whisper_size=self.cfg.whisper_size)
            self._ears.start()
        return self._ears

    def speak(self, text: str, rate: int = 175, pitch: int = 0) -> None:
        from .voice import speak

        speak(text, self.cfg.voice, enabled=True, rate=rate, pitch=self.cfg.pitch + pitch)

    def listen(self) -> str:
        return self._ensure_ears().listen()

    def look(self) -> Dict:
        from . import eyes

        ok, why = eyes.available()
        if not ok:
            return {"text": why, "n_faces": 0, "n_looking": 0}
        return eyes.Eye().look()

    def face(self, emotion: str) -> None:
        """脸是另一个窗口（face.py）。它没开着就静默跳过，别影响说话。"""
        import urllib.request

        try:
            urllib.request.urlopen(
                "http://127.0.0.1:8770/emotion?name=%s" % emotion, timeout=1
            ).read()
        except Exception:  # noqa: BLE001
            pass

    def close(self) -> None:
        if self._ears is not None:
            self._ears.stop()
            self._ears = None


class NetBody(Body):
    """把四个动作发到局域网上的一个设备（ESP32 / 树莓派）。

    设备那头要实现四个接口，见 docs/设备协议.md。
    故意用最笨的 HTTP：不用 WebSocket、不用自研二进制协议 —— 板子那头的
    调试成本越低越好，真出问题时用浏览器就能测。
    """

    name = "net"

    def __init__(self, cfg):
        self.base = (cfg.body_url or "").rstrip("/")
        if not self.base:
            raise BodyError("config.json 里 body_url 是空的。")
        self.timeout = float(getattr(cfg, "body_timeout", 30))

    def _post(self, path: str, payload: dict, timeout: Optional[float] = None):
        req = urllib.request.Request(
            self.base + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            raise BodyError("设备返回 %d（%s）" % (e.code, path)) from e
        except urllib.error.URLError as e:
            raise BodyError("连不上设备 %s（%s）" % (self.base, e.reason)) from e
        except TimeoutError as e:
            raise BodyError("设备超时（%s）" % path) from e

    def speak(self, text: str, rate: int = 175, pitch: int = 0) -> None:
        # 说：把文本和语速给设备，让它自己用板上 TTS，
        # 或者（推荐）由这边合成好 PCM 推过去 —— 见协议文档的 /speak_pcm
        self._post("/speak", {"text": text, "rate": rate, "pitch": pitch}, timeout=120)

    def listen(self) -> str:
        r = self._post("/listen", {"seconds": 20}, timeout=40)
        return str(r.get("text", ""))

    def look(self) -> Dict:
        return self._post("/look", {}, timeout=30)

    def face(self, emotion: str) -> None:
        try:
            self._post("/face", {"emotion": emotion}, timeout=10)
        except BodyError:
            pass  # 表情失败不影响主流程


def make_body(cfg) -> Body:
    kind = (getattr(cfg, "body", "mac") or "mac").lower()
    if kind == "net":
        return NetBody(cfg)
    return MacBody(cfg)
