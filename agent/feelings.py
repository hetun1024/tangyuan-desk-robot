"""情绪：一个很小、很慢、会因为发生的事而变、也会自己回到平静的状态。

设计上有三条硬规矩，不然就是假情绪：

1. **慢**。一次夸奖只加一点点，一次冷落只减一点点。刷一次不会变成另一个人。
2. **会退**。不做任何事，它会自己漂回基线。没有这条，情绪会一直往下掉，
   最后变成一台抑郁的机器 —— 那不是陪伴，是负担。
3. **能说清为什么**。每一笔变动都记在一个小本子上（事件 + 当时的时间），
   所以它被问"你怎么了"的时候，能说出"你今天三次没理我"。

存盘在 data/feelings.json —— 关掉程序再打开，它还是那个心情。
"""
from __future__ import annotations

import datetime as _dt
import json
import math
import os
from dataclasses import dataclass, field
from typing import List, Optional

BASELINE_VALENCE = 0.05
BASELINE_ENERGY = 0.55
MAX_EVENTS = 60


def _now() -> _dt.datetime:
    return _dt.datetime.now()


@dataclass
class Feelings:
    path: str
    valence: float = BASELINE_VALENCE  # -1 难过 … +1 开心
    energy: float = BASELINE_ENERGY  # 0 困 … 1 兴奋
    intimacy: float = 0.0  # 0 陌生 … 1 很熟
    last_seen: str = ""
    last_spoke: str = ""
    days: List[str] = field(default_factory=list)
    first_met: str = ""  # 认识的第一天
    events: List[dict] = field(default_factory=list)
    session_gap: float = 0.0  # 这次启动前隔了几小时（不存盘）

    # ------------------------------------------------------------------ 存读
    @classmethod
    def load(cls, path: str) -> "Feelings":
        f = cls(path=path)
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            for k in ("valence", "energy", "intimacy"):
                setattr(f, k, float(data.get(k, getattr(f, k))))
            f.last_seen = data.get("last_seen", "")
            f.last_spoke = data.get("last_spoke", "")
            f.days = list(data.get("days") or [])
            f.first_met = data.get("first_met", "")
            f.events = list(data.get("events") or [])
        except Exception:  # noqa: BLE001
            pass
        return f

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "valence": round(self.valence, 4),
                    "energy": round(self.energy, 4),
                    "intimacy": round(self.intimacy, 4),
                    "last_seen": self.last_seen,
                    "last_spoke": self.last_spoke,
                    "days": self.days[-400:],
                    "first_met": self.first_met,
                    "events": self.events[-MAX_EVENTS:],
                },
                fh,
                ensure_ascii=False,
                indent=1,
            )

    # ------------------------------------------------------------------ 时间
    def tick(self, now: Optional[_dt.datetime] = None) -> None:
        """不做任何事也会发生的事：情绪漂回基线，关系慢慢变淡。"""
        now = now or _now()
        hours = self._hours_since(self.last_seen, now) if self.last_seen else 0.0

        # 回落到基线：离开越久，回得越多。刚关掉就打开几乎不变 ——
        # 否则你聊得正开心，重启一次她就"失忆"了。
        if hours < 2:
            rate = 0.05
        elif hours < 8:
            rate = 0.18
        elif hours < 24:
            rate = 0.38
        else:
            rate = 0.55
        self.valence += (BASELINE_VALENCE - self.valence) * rate
        # 精力不只是"回基线"，还跟着一天的时间走 —— 这是"作息"
        self.energy += (_circadian_energy(now.hour) - self.energy) * rate

        # 太久没见，关系会淡一点点（但很慢，别一天就变陌生人）
        if hours > 24:
            self.intimacy = max(0.0, self.intimacy - min(0.08, (hours - 24) / 24 * 0.02))

    @staticmethod
    def _hours_since(stamp: str, now: _dt.datetime) -> float:
        try:
            then = _dt.datetime.fromisoformat(stamp)
        except Exception:  # noqa: BLE001
            return 0.0
        return max(0.0, (now - then).total_seconds() / 3600.0)

    # ------------------------------------------------------------------ 事件
    def event(self, kind: str, detail: str = "", now: Optional[_dt.datetime] = None) -> None:
        """记一笔，并改动状态。改动都很小 —— 一次不够，几次才看得出来。"""
        now = now or _now()
        dv, de, di = {
            "praise": (0.12, 0.05, 0.04),
            "ignored": (-0.10, -0.05, -0.02),
            "return": (0.08, 0.10, 0.02),
            "task_done": (0.07, 0.03, 0.02),
            "task_failed": (-0.05, -0.02, 0.0),
            "late_night": (-0.02, -0.18, 0.0),
            "long_absence": (-0.18, -0.10, -0.05),
            "joke": (0.10, 0.06, 0.03),
            "chat": (0.035, 0.015, 0.012),
            "petted": (0.11, 0.06, 0.05),
            "held": (0.07, 0.03, 0.04),
            "dropped": (-0.04, 0.02, -0.01),
            "dark": (0.0, -0.10, 0.0),
            "user_low": (0.0, -0.10, 0.03),
            "user_high": (0.04, 0.08, 0.02),
        }.get(kind, (0.0, 0.0, 0.0))

        self.valence = _clamp(self.valence + dv, -1.0, 1.0)
        self.energy = _clamp(self.energy + de, 0.0, 1.0)
        self.intimacy = _clamp(self.intimacy + di, 0.0, 1.0)
        self._note(kind, detail, now)

    def _note(self, kind: str, detail: str, now: _dt.datetime):
        self.events.append(
            {"t": now.isoformat(timespec="seconds"), "kind": kind, "detail": detail[:80]}
        )
        self.events = self.events[-MAX_EVENTS:]

    STAGES = [(0, "刚认识"), (3, "有点熟了"), (7, "习惯你在"), (30, "老朋友"), (100, "离不开")]

    @property
    def stage(self) -> str:
        """养成感：不是一个数字，是一句人话。"""
        d = self.days_known
        name = self.STAGES[0][1]
        for need, label in self.STAGES:
            if d >= need:
                name = label
        return name

    @property
    def traits(self) -> Dict[str, float]:
        """性格不是设定的，是**被相处出来的**。

        被夸得多 → 黏人；被冷落得多 → 独立；深夜聊得多 → 夜猫子。
        各算一个 0—1 的强度，写进提示词让模型照着演。
        """
        kinds = [e.get("kind") for e in self.events[-40:]]
        n = max(len(kinds), 1)
        clingy = sum(1 for k in kinds if k in ("praise", "petted", "held", "chat")) / n
        independent = sum(1 for k in kinds if k in ("ignored", "long_absence")) / n
        night = sum(1 for k in kinds if k == "late_night") / n
        return {"黏人": round(clingy, 2), "独立": round(independent, 2), "夜猫子": round(night, 2)}

    def trait_word(self) -> str:
        t = self.traits
        best = max(t, key=t.get)
        if t[best] < 0.15:
            return "还没定型"
        return best

    @property
    def days_known(self) -> int:
        try:
            d0 = _dt.date.fromisoformat(self.first_met[:10])
        except Exception:  # noqa: BLE001
            return 0
        return (_dt.date.today() - d0).days + 1

    @property
    def sulk(self) -> bool:
        """隔了很久才回来，而且心情本来就低 —— 这时候要先闹一下别扭。"""
        return self.session_gap > 18 and self.valence < 0.1

    def start_session(self, now: Optional[_dt.datetime] = None) -> float:
        """每次启动调一次：返回"这次隔了多久"，并按隔了多久影响情绪。"""
        now = now or _now()
        gap = self.hours_since_seen()
        self.session_gap = gap
        self.tick(now)
        if gap > 24:
            self.event("long_absence", "%.0f 小时没见" % gap, now)
        elif gap > 3:
            self.event("return", "", now)
        self.last_seen = now.isoformat(timespec="seconds")
        today = now.strftime("%Y-%m-%d")
        if not self.days or self.days[-1] != today:
            self.days.append(today)
        if not self.first_met:
            self.first_met = now.isoformat(timespec="seconds")
        self.save()
        return gap

    def mark_spoke(self, now: Optional[_dt.datetime] = None):
        now = now or _now()
        self.last_spoke = now.isoformat(timespec="seconds")
        self.last_seen = self.last_spoke
        today = now.strftime("%Y-%m-%d")
        if not self.days or self.days[-1] != today:
            self.days.append(today)

    # ------------------------------------------------------------ 给自己看
    @property
    def streak_days(self) -> int:
        return len(self.days)

    @property
    def mood_word(self) -> str:
        """用词要和 face.py 的脸色对得上，不然嘴上说平静、脸上在笑。"""
        v, e = self.valence, self.energy
        if v > 0.40:
            return "喜欢" if e > 0.5 else "挺高兴"
        if v > 0.15:
            return "有点开心"
        if v < -0.25:
            return "有点难过" if e < 0.4 else "有点烦躁"
        if e < 0.30:
            return "有点困"
        if e > 0.80:
            return "很兴奋"
        return "平静"

    def hours_since_seen(self) -> float:
        return self._hours_since(self.last_seen, _now()) if self.last_seen else 0.0

    def prompt(self) -> str:
        """给模型看的一段自述。不是数据，是第一人称。"""
        hours = max(self.session_gap, self.hours_since_seen())
        if hours < 0.1:
            gap = "刚刚还在说话"
        elif hours < 3:
            gap = "%.0f 小时前聊过" % hours
        else:
            gap = "已经 %.0f 小时没见了" % hours

        bits = [
            "你现在的心情：%s（愉悦 %.2f，精力 %.2f）。" % (self.mood_word, self.valence, self.energy),
            "你和这个人的熟悉程度：%s（%.2f）。" % (_intimacy_word(self.intimacy), self.intimacy),
            "上次说话：%s。" % gap,
        ]
        if self.days_known > 1:
            bits.append("今天是你们认识的第 %d 天（%s）。" % (self.days_known, self.stage))
        tw = self.trait_word()
        if tw != "还没定型":
            bits.append("被相处出来的性格：偏%s。" % tw)
        hour = _now().hour
        if hour >= 23 or hour < 6:
            bits.append("现在是深夜，你有点困，说话应该更短更慢。")
        elif hour < 9:
            bits.append("现在是早上，你刚醒，还有点没精神。")
        if self.sulk:
            bits.append("他隔了很久才回来。你有点别扭：先别太热情，两句话之后再软下来。")
        recent = [e for e in self.events[-3:] if e.get("kind") in ("ignored", "praise", "long_absence", "petted")]
        if recent:
            bits.append("最近发生的事：" + "；".join(_describe(e) for e in recent))
        bits.append("（情绪只是语气和态度，别反复说「我有点难过」这种话，更别拿它要挟人。）")
        return "\n" + "\n".join(bits) + "\n"

    # -------------------------------------------------------- 影响说话方式
    def voice_rate(self, base: int = 175) -> int:
        """心情低 → 说慢；兴奋 → 说快。"""
        return int(_clamp(base + (self.energy - 0.5) * 40 + self.valence * 10, 140, 210))

    def voice_pitch(self, base: int = 0) -> int:
        """开心的时候调门会高一点。"""
        return int(_clamp(base + self.valence * 12, -20, 20))


def _circadian_energy(hour: int) -> float:
    """一天里的精力曲线：凌晨最低，白天回升，傍晚最高。"""
    if 0 <= hour < 6:
        return 0.22
    if 6 <= hour < 9:
        return 0.45
    if 9 <= hour < 18:
        return 0.62
    if 18 <= hour < 23:
        return 0.58
    return 0.35


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def _intimacy_word(v: float) -> str:
    if v < 0.15:
        return "还不太熟"
    if v < 0.4:
        return "开始熟了"
    if v < 0.7:
        return "挺熟"
    return "很熟"


def _describe(e: dict) -> str:
    return {
        "ignored": "被冷落了一会儿",
        "praise": "被夸了",
        "petted": "被摸了头",
        "held": "被抱起来",
        "long_absence": "很久没见面",
        "task_done": "帮你做成了一件事",
        "late_night": "很晚了",
    }.get(e.get("kind", ""), e.get("kind", ""))
