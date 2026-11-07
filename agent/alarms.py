"""闹钟：到点就叫你。

设计上只有一条要注意的：**她在等你说活的时候是"阻塞"的**，
所以闹钟不可能精确到毫秒。主循环每轮结束检查一次，误差最多一个 listen 周期
（约 10 秒）。对"提醒我十分钟后喝水"这种事完全够用。

响过的闹钟会被标记成 done，不会重复叫。进程关掉再打开也会检查一次：
关机期间错过的，会告诉你"错过了一个"。

存盘在 data/alarms.json。
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from typing import Dict, List, Optional


class Alarms:
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
            json.dump({"items": self.items[-50:]}, fh, ensure_ascii=False, indent=1)

    # ------------------------------------------------------------------ 增
    def add(self, when: str, what: str) -> str:
        what = (what or "").strip()[:80] or "闹钟"
        when = (when or "").strip()
        try:
            target = _parse(when)
        except ValueError as e:
            return str(e)
        if target <= _dt.datetime.now():
            return "这个时间已经过去了。"
        self.items.append(
            {"at": target.isoformat(timespec="seconds"), "what": what, "done": False}
        )
        self.save()
        return "好，%s 叫你%s。" % (target.strftime("%H:%M"), what)

    def cancel(self, index: int) -> str:
        if not (0 <= index < len(self.items)):
            return "没有第 %d 条。" % index
        item = self.items.pop(index)
        self.save()
        return "取消了 %s 的「%s」。" % (item["at"][11:16], item["what"])

    # ------------------------------------------------------------------ 查
    def pending(self) -> List[Dict]:
        return [i for i in self.items if not i.get("done")]

    def due(self, now: Optional[_dt.datetime] = None) -> List[Dict]:
        now = now or _dt.datetime.now()
        fired = []
        for i in self.items:
            if i.get("done"):
                continue
            try:
                at = _dt.datetime.fromisoformat(i["at"])
            except Exception:  # noqa: BLE001
                continue
            if at <= now:
                i["done"] = True
                fired.append(i)
        if fired:
            self.save()
        return fired

    def list_text(self) -> str:
        pend = sorted(self.pending(), key=lambda i: i["at"])
        if not pend:
            return "没有设闹钟。"
        return "\n".join(
            "%d. %s %s" % (n, i["at"][11:16], i["what"]) for n, i in enumerate(pend)
        )


def _parse(when: str) -> _dt.datetime:
    """认三种写法：完整时间、今天/明天的 HH:MM、相对分钟数。"""
    now = _dt.datetime.now()
    when = when.strip()

    try:  # ISO 格式（in_minutes 生成的就是这个）
        return _dt.datetime.fromisoformat(when)
    except ValueError:
        pass

    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return _dt.datetime.strptime(when, fmt)
        except ValueError:
            pass

    # "07:30" / "7:30" → 今天；已经过了就算明天
    if ":" in when and len(when) <= 5:
        try:
            h, m = when.split(":")
            t = now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
            return t if t > now else t + _dt.timedelta(days=1)
        except ValueError:
            pass

    raise ValueError("时间看不懂。可以写 2026-11-06 15:30，或者 07:30，或者分钟数。")


def in_minutes(minutes: float) -> str:
    return (_dt.datetime.now() + _dt.timedelta(minutes=float(minutes))).isoformat(
        timespec="seconds"
    )
