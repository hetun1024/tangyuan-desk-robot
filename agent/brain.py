"""大脑：一次对话请求。

只依赖标准库（urllib），不装任何 SDK。原因有两个：
  1. 少一个依赖，就少一个在机器人板子上装不上的东西；
  2. 所有主流服务（DeepSeek / 通义 / 智谱 / Kimi / OpenAI）都是同一套
     OpenAI 兼容接口，换个 base_url 和 model 就能换大脑。

工具调用用的是接口原生的 function calling，不是让模型"输出 JSON 再解析"——
后者在中文模型上经常多写一句话就崩了。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from .config import Config


class BrainError(RuntimeError):
    pass


class Brain:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.3,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": self.cfg.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        req = urllib.request.Request(
            self.cfg.base_url + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.cfg.api_key,
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.cfg.timeout_s) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8")[:400]
            except Exception:  # noqa: BLE001
                pass
            if e.code == 401:
                raise BrainError("API key 不对（401）。检查 config.json 里的 api_key。") from e
            if e.code == 402:
                raise BrainError("账户没钱了（402）。去充值，或者换个模型。") from e
            if e.code == 429:
                raise BrainError("请求太频繁被限流（429）。等几秒再问。") from e
            raise BrainError("服务返回 %d：%s" % (e.code, detail)) from e
        except urllib.error.URLError as e:
            raise BrainError(
                "连不上 %s。\n检查网络，或者把 config.json 里的 base_url 换成能通的地址。\n（%s）"
                % (self.cfg.base_url, e.reason)
            ) from e
        except TimeoutError as e:
            raise BrainError("等了 %d 秒没回。网络慢，或者问题太长。" % self.cfg.timeout_s) from e

        try:
            msg = body["choices"][0]["message"]
        except (KeyError, IndexError) as e:
            raise BrainError("返回格式看不懂：%s" % str(body)[:300]) from e

        return {
            "content": msg.get("content") or "",
            "tool_calls": msg.get("tool_calls") or [],
        }# 
