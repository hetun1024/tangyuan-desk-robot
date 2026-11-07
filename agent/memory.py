"""长期记忆：让它记得你是谁。

为什么这一层最影响"傻不傻"：一个每次都问"你叫什么"的助手，不管模型多强，
用起来都像个陌生程序。记忆不在模型里，在磁盘上 —— 一个 json，几百字节，
但决定了它是不是"认得你"。

设计上只做一件事：**键值对 + 每次对话前塞进系统提示**。
不做向量检索、不做摘要链路 —— 那些是给几万条记忆准备的，你只有几十条。
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from typing import Dict, List, Optional

MAX_FACTS = 60


def _today() -> str:
    return _dt.date.today().isoformat()


class Memory:
    def __init__(self, path: str):
        self.path = path
        self.facts: Dict[str, str] = {}
        self.private: Dict[str, str] = {}  # 知道、但绝不主动提的事
        self.load()

    # ------------------------------------------------------------------ io
    def load(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
            self.facts = dict(data.get("facts") or {})
            self.private = dict(data.get("private") or {})
        except Exception:  # noqa: BLE001
            self.facts = {}
            self.private = {}

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "facts": self.facts,
                    "private": self.private,
                    "updated": _dt.datetime.now().isoformat(timespec="seconds"),
                },
                fh,
                ensure_ascii=False,
                indent=1,
            )

    # --------------------------------------------------------------- 增删查
    def set(self, key: str, value: str) -> str:
        key = (key or "").strip()[:40]
        value = (value or "").strip()[:300]
        if not key or not value:
            return "键或值不能为空。"
        if key not in self.facts and len(self.facts) >= MAX_FACTS:
            # 满了就挤掉最淡的一条，而不是最早的一条
            weakest = min(self.facts, key=lambda k: self._rel(self.facts[k]))
            self.facts.pop(weakest, None)
        self.facts[key] = {"v": value, "rel": 1.0, "used": _today(), "hits": 1}
        self.save()
        return "记住了：%s = %s" % (key, value)

    @staticmethod
    def _rel(item) -> float:
        return float(item.get("rel", 1.0)) if isinstance(item, dict) else 1.0

    @staticmethod
    def _val(item) -> str:
        return str(item.get("v", "")) if isinstance(item, dict) else str(item)

    def get(self, key: str) -> str:
        return self._val(self.facts.get(key, ""))

    def touch(self, key: str) -> None:
        """被用到一次，就记得更牢一点。"""
        item = self.facts.get(key)
        if not isinstance(item, dict):
            return
        item["rel"] = min(1.0, self._rel(item) + 0.15)
        item["hits"] = int(item.get("hits", 0)) + 1
        item["used"] = _today()

    def decay(self) -> None:
        """忘掉一点。这是记忆该有的样子 —— 不常提的事会淡。"""
        for item in self.facts.values():
            if not isinstance(item, dict):
                continue
            try:
                days = (_dt.date.today() - _dt.date.fromisoformat(str(item.get("used"))[:10])).days
            except Exception:  # noqa: BLE001
                days = 0
            item["rel"] = max(0.1, float(item.get("rel", 1.0)) - days * 0.03)

    def set_private(self, key: str, value: str) -> str:
        key = (key or "").strip()[:40]
        value = (value or "").strip()[:300]
        if not key or not value:
            return "键或值不能为空。"
        self.private[key] = value
        self.save()
        return "记下了，这件事不主动提。"

    def drop(self, key: str) -> str:
        if key in self.facts or key in self.private:
            self.facts.pop(key, None)
            self.private.pop(key, None)
            self.save()
            return "忘掉了：%s" % key
        return "没有这条记忆：%s" % key

    def search(self, keyword: str = "") -> List[str]:
        if not keyword:
            return ["%s：%s" % (k, self._val(v)) for k, v in self.facts.items()]
        return [
            "%s：%s" % (k, self._val(v))
            for k, v in self.facts.items()
            if keyword in k or keyword in self._val(v)
        ]

    def faint(self) -> List[str]:
        """快忘掉的那些。偶尔翻出来，像"咦，你还提过这个"。"""
        out = [(k, self._val(v)) for k, v in self.facts.items() if self._rel(v) < 0.5]
        return ["%s：%s" % kv for kv in out]

    # ------------------------------------------------------------- 给模型看
    def prompt(self) -> str:
        if not self.facts:
            return (
                "\n（你还不认识这个用户。第一两次对话里自然地了解他叫什么、"
                "在做什么，然后用 remember_fact 记下来。）\n"
            )
        self.decay()
        strong = sorted(self.facts.items(), key=lambda kv: -self._rel(kv[1]))
        strong = [(k, v) for k, v in strong if self._rel(v) >= 0.35][:20]
        weak = [k for k, v in self.facts.items() if self._rel(v) < 0.35]
        for k, _ in strong:
            self.touch(k)

        lines = "\n".join("- %s：%s" % (k, self._val(v)) for k, v in strong)
        out = "\n关于这个用户，你记得这些：\n%s\n" % (lines or "（暂时想不起什么）")
        if weak:
            out += "\n（有几件事你记不太清了：%s。如果聊到，就说「好像听你提过」，别编。）\n" % "、".join(weak[:5])
        if self.private:
            out += (
                "\n这些是他不太想被提起的事。你知道，但**绝对不要主动提**，"
                "除非他自己先说：\n%s\n"
                % "\n".join("- %s：%s" % (k, v) for k, v in self.private.items())
            )
        return out
