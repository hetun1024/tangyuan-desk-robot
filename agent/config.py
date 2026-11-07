"""配置：一个 json 文件，或者环境变量。

优先级：环境变量 > config.json > 默认值。
这样做是为了以后搬上机器人：板子上没有 config.json，用环境变量就行。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

DEFAULTS = {
    "name": "汤圆",
    "base_url": "https://api.deepseek.com/v1",
    "model": "deepseek-chat",
    "api_key": "",
    "voice": "zh-CN-XiaoxiaoNeural",
    "asr": "whisper",
    "whisper_size": "small",
    "vision_base_url": "https://open.bigmodel.cn/api/paas/v4",
    "vision_model": "glm-4v-flash",
    "vision_api_key": "",
    "wake_word": "汤圆",
    "require_wake": True,
    "body": "mac",
    "body_url": "",
    "body_timeout": 30,
    "pitch": 0,
    "max_steps": 5,
    "timeout_s": 60,
    "allow_shell": False,
}


@dataclass
class Config:
    name: str = DEFAULTS["name"]
    base_url: str = DEFAULTS["base_url"]
    model: str = DEFAULTS["model"]
    api_key: str = ""
    voice: str = DEFAULTS["voice"]
    pitch: int = 0
    vision_base_url: str = DEFAULTS["vision_base_url"]
    vision_model: str = DEFAULTS["vision_model"]
    vision_api_key: str = ""
    wake_word: str = "汤圆"
    require_wake: bool = True
    body: str = "mac"
    body_url: str = ""
    body_timeout: int = 30
    asr: str = DEFAULTS["asr"]
    whisper_size: str = DEFAULTS["whisper_size"]
    max_steps: int = DEFAULTS["max_steps"]
    timeout_s: int = 60
    allow_shell: bool = False

    @classmethod
    def load(cls, path: str | None = None) -> "Config":
        raw = dict(DEFAULTS)

        candidates = [path] if path else ["config.json", os.path.expanduser("~/.robot-brain.json")]
        for c in candidates:
            if c and os.path.exists(c):
                with open(c, encoding="utf-8") as fh:
                    raw.update({k: v for k, v in json.load(fh).items() if v != ""})
                break

        env_map = {
            "OPENAI_BASE_URL": "base_url",
            "OPENAI_MODEL": "model",
            "OPENAI_API_KEY": "api_key",
            "ROBOT_VOICE": "voice",
        }
        for env, key in env_map.items():
            if os.environ.get(env):
                raw[key] = os.environ[env]

        return cls(
            name=str(raw.get("name") or DEFAULTS["name"]),
            base_url=str(raw["base_url"]).rstrip("/"),
            model=str(raw["model"]),
            api_key=str(raw["api_key"]),
            voice=str(raw["voice"]),
            pitch=int(raw.get("pitch") or 0),
            vision_base_url=str(raw.get("vision_base_url") or DEFAULTS["vision_base_url"]),
            vision_model=str(raw.get("vision_model") or DEFAULTS["vision_model"]),
            vision_api_key=str(raw.get("vision_api_key") or ""),
            wake_word=str(raw.get("wake_word") or "汤圆"),
            require_wake=bool(raw.get("require_wake", True)),
            body=str(raw.get("body") or "mac"),
            body_url=str(raw.get("body_url") or ""),
            body_timeout=int(raw.get("body_timeout") or 30),
            asr=str(raw.get("asr") or DEFAULTS["asr"]),
            whisper_size=str(raw.get("whisper_size") or DEFAULTS["whisper_size"]),
            max_steps=int(raw["max_steps"]),
            timeout_s=int(raw["timeout_s"]),
            allow_shell=bool(raw["allow_shell"]),
        )

    def check(self) -> str | None:
        """返回人话错误，没问题就返回 None。"""
        if not self.api_key:
            return (
                "还没填 API key。\n"
                "打开 config.json，把 api_key 那一行填上你自己申请的 key，存盘，再运行。\n"
                "（别把 key 发给任何人，包括我。）"
            )
        return None
