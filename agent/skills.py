"""技能包：一份长文档按需注入。

为什么不是"全部塞进提示词"：
情绪类的守则动辄上千行，常驻会把上下文吃光，还会让她每句话都像心理咨询师。

做法：每个技能一个目录

    skills/<名字>/
        守则.md      要注入的正文
        trigger.txt  触发词，一行一个

只有用户这句话里出现触发词，才把对应守则拼进系统提示。平时零成本。
"""
from __future__ import annotations

import os
from typing import Dict, List


class Library:
    def __init__(self, root: str):
        self.root = root
        self.skills: Dict[str, dict] = {}
        self._load()

    def _load(self):
        if not os.path.isdir(self.root):
            return
        for name in sorted(os.listdir(self.root)):
            d = os.path.join(self.root, name)
            body = os.path.join(d, "守则.md")
            trig = os.path.join(d, "trigger.txt")
            if not (os.path.isdir(d) and os.path.exists(body)):
                continue
            try:
                text = open(body, encoding="utf-8").read().strip()
                words = []
                if os.path.exists(trig):
                    words = [w.strip() for w in open(trig, encoding="utf-8") if w.strip()]
            except Exception:  # noqa: BLE001
                continue
            self.skills[name] = {"text": text, "words": words}

    def match(self, text: str) -> List[str]:
        """返回这一轮该加载的守则正文。"""
        t = text or ""
        out = []
        for name, sk in self.skills.items():
            if any(w in t for w in sk["words"]):
                out.append(sk["text"])
        return out

    def prompt(self, text: str) -> str:
        parts = self.match(text)
        if not parts:
            return ""
        return "\n\n（这一轮有额外的行为守则，优先遵守：）\n" + "\n\n---\n\n".join(parts) + "\n"

    def names(self) -> List[str]:
        return sorted(self.skills)
