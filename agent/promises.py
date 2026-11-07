"""约定：她记得你答应过的事。

这是七个功能里最像"有人在意你"的一个，也是实现最简单的一个 ——
一个 json，几条 {什么事, 哪天, 做没做}。

关键在于**由谁来定日期**：让人去解析"明天下午"太脆，让模型自己算好再填
YYYY-MM-DD 反而稳，因为它已经知道今天几号（get_time 工具）。
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from typing import Dict, List, Optional


class Promises:
    def __init__(self, path: str):
        self.path = path
        self.items: List[Dict] = []
        self.load()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                self.items = list(json.load(fh).get("items") or [])
        except Exception:  # noqa: BLE001
            self.items = []

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"items": self.items[-100:]}, fh, ensure_ascii=False, indent=1)

    # ------------------------------------------------------------------ 增
    def add(self, what: str, due: str) -> str:
        what = (what or "").strip()[:120]
        due = (due or "").strip()[:10]
        if not what:
            return "要记什么？"
        try:
            d = _dt.date.fromisoformat(due)
        except ValueError:
            return "日期要 YYYY-MM-DD 这种写法，比如 2026-11-06。"
        if d < _dt.date.today():
            return "这个日期已经过去了。"
        self.items.append(
            {
                "what": what,
                "due": due,
                "done": False,
                "created": _dt.datetime.now().isoformat(timespec="seconds"),
            }
        )
        self.save()
        return "记下了：%s 号提醒你「%s」。" % (due, what)

    def done(self, index: int) -> str:
        if not (0 <= index < len(self.items)):
            return "没有第 %d 条。" % index
        self.items[index]["done"] = True
        self.save()
        return "这条算完了：%s" % self.items[index]["what"]

    # ------------------------------------------------------------------ 查
    def pending(self) -> List[Dict]:
        return [i for i in self.items if not i.get("done")]

    def due_today(self, today: Optional[_dt.date] = None) -> List[Dict]:
        today = today or _dt.date.today()
        return [i for i in self.pending() if i.get("due") == today.isoformat()]

    def overdue(self, today: Optional[_dt.date] = None) -> List[Dict]:
        today = today or _dt.date.today()
        return [i for i in self.pending() if i.get("due", "9999") < today.isoformat()]

    # ------------------------------------------------------------- 给模型看
    def prompt(self, today: Optional[_dt.date] = None) -> str:
        today = today or _dt.date.today()
        due = self.due_today(today)
        late = self.overdue(today)
        lines = []
        for i in due:
            lines.append("今天答应过要问的事：%s" % i["what"])
        for i in late:
            lines.append("过期没问的事（%s）：%s" % (i["due"], i["what"]))
        if not lines:
            up = self.pending()[:3]
            if not up:
                return ""
            lines = ["以后要记得的事：" + "；".join("%s（%s）" % (i["what"], i["due"]) for i in up)]
        return "\n" + "\n".join(lines) + "\n"
