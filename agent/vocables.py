"""拟声词：不说人话的那部分。

桌宠真正像活物，靠的不是每次都说一句完整的话，而是这些很短的、没有语法噪音：

    被叫到  嗯？
    想事情  唔……
    被夸    诶嘿
    不高兴  哼
    困      呼——

关键是**克制**。每句都"嗯？"会烦，所以这里控制了频率：默认最多每 3 轮出一次，
而且几种声音各有各的触发条件。
"""
from __future__ import annotations

import random
import re

# 每种心情对应的几个短音，随机取一个，避免每次一模一样
VOCABLES = {
    "called": ["嗯？", "欸？", "在呢"],
    "thinking": ["唔……", "嗯……", "让我想想"],
    "praise": ["诶嘿", "嘿嘿", "唔嗯～"],
    "annoyed": ["哼", "哼嗯", "……哦"],
    "sleepy": ["呼——", "唔……", "困了"],
    "care": ["怎么啦", "嗯？怎么了"],
}

PRAISE = ("喜欢你", "好可爱", "真可爱", "好棒", "真棒", "厉害", "爱你", "好乖", "真乖", "聪明", "真好")
TIRED = ("好累", "累死", "有点累", "太累", "困", "想睡", "疲惫", "没力气")
SAD = ("难过", "不开心", "烦", "委屈", "崩溃", "想哭")


def detect(text: str) -> str | None:
    """从用户这句话里读出一个事件，没有就返回 None。"""
    t = text or ""
    if any(w in t for w in PRAISE):
        return "praise"
    if any(w in t for w in SAD):
        return "sad"
    if any(w in t for w in TIRED):
        return "tired"
    if any(w in t for w in ("在吗", "在不在", "汤圆")):
        return "called"
    if re.fullmatch(r"[喂哎诶欸嗯啊哦]+[？?]?", t.strip()):
        return "called"
    return None


class Voice:
    """管频率：别每句都出声。"""

    def __init__(self, min_gap: int = 3, chance: float = 0.55, seed=None):
        self.min_gap = min_gap
        self.chance = chance
        self.rng = random.Random(seed)
        self.turns = 0
        self.last = -99

    def maybe(self, kind: str | None) -> str | None:
        """给个事件类型，返回要不要出声、出哪句。"""
        self.turns += 1
        if not kind:
            return None
        # 被夸、被叫到这种，不用等冷却 —— 那是"被点名"，必须应
        urgent = kind in ("praise", "called")
        if not urgent and self.turns - self.last < self.min_gap:
            return None
        if not urgent and self.rng.random() > self.chance:
            return None
        self.last = self.turns
        return self.rng.choice(VOCABLES.get(kind, ["嗯"]))
