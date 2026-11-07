"""读空气：从**用户这句话**里读出他此刻的状态，然后换一种应对方式。

它跟 feelings.py 是两件事：
  * feelings  是"她自己"的心情
  * room      是"对方"的状态 —— 他急了、他怀疑、他很谨慎、他满意了

为什么要有这一层：同样一句"帮我改一下"，
  在他很急的时候 → 少铺垫，直接给结果
  在他怀疑的时候 → 先给依据，再动手
  在他很谨慎的时候 → 把范围收窄，别顺手扩展
  在他已经满意的时候 → 收口，别再加东西

信号不看内容看**形状**：标点密度、句子长度、催促词、反问、重复。

这个思路来自 emotion-skill（原作者仓库已 404），这里是一个轻量重写：
不跑语义模型，只做可解释的规则，输出一段话给模型当"应对方式"。
"""
from __future__ import annotations

import re
from typing import Dict, List

URGENT = ("快点", "赶紧", "马上", "急", "立刻", "现在就要", "来不及", "催")
DOUBT = ("真的吗", "确定吗", "你确定", "不可能", "怎么会", "靠不靠", "靠谱吗", "是不是骗")
CAUTION = ("可能", "也许", "不一定", "大概", "谨慎", "小心", "先别", "稳妥")
SATISFIED = ("谢谢", "好的", "可以了", "完美", "就这样", "够了", "搞定", "辛苦了")
LOW = ("难过", "累", "烦", "委屈", "不开心", "崩溃", "想哭", "压力")

OVERLAY = {
    "act_fast": "他很急。少铺垫，先给结果，过程能省就省。",
    "show_basis": "他在怀疑。先给依据或证据，再动手；别用「应该没问题」这种话。",
    "narrow_scope": "他很谨慎。把范围收窄，只做确定的部分，别顺手扩展。",
    "close_it": "他已经满意了。别再改别再加，收口确认一句就停。",
    "comfort": "他状态不好。先接住情绪，别急着给方案。一两句话就够。",
    "normal": "",
}


def _punct_density(t: str) -> float:
    if not t:
        return 0.0
    return sum(1 for c in t if c in "！!？?") / max(len(t), 1)


def read(text: str, prev: List[str] | None = None) -> Dict:
    """返回 {mode, score, overlay}。mode 决定这一轮谁来主导。"""
    t = (text or "").strip()
    prev = prev or []
    scores = {"act_fast": 0.0, "show_basis": 0.0, "narrow_scope": 0.0,
              "close_it": 0.0, "comfort": 0.0}

    if not t:
        return {"mode": "normal", "scores": scores, "overlay": ""}

    # 急：短 + 标点密 + 催促词 + 上一句也在催
    if len(t) <= 12:
        scores["act_fast"] += 0.3
    scores["act_fast"] += min(0.4, _punct_density(t) * 2.0)
    scores["act_fast"] += 0.4 if any(w in t for w in URGENT) else 0.0
    if prev and any(w in prev[-1] for w in URGENT):
        scores["act_fast"] += 0.3

    # 怀疑：反问 + 怀疑词 + 重复提问
    if any(w in t for w in DOUBT):
        scores["show_basis"] += 0.8
    if "？" in t or "?" in t:
        scores["show_basis"] += 0.15
    if prev and t and t == prev[-1]:
        scores["show_basis"] += 0.5  # 同一句重复问 = 不信

    if any(w in t for w in CAUTION):
        scores["narrow_scope"] += 0.7

    if any(w in t for w in SATISFIED):
        scores["close_it"] += 0.9

    if any(w in t for w in LOW):
        scores["comfort"] += 0.9

    mode = max(scores, key=scores.get)
    if scores[mode] < 0.5:
        mode = "normal"
    return {"mode": mode, "scores": {k: round(v, 2) for k, v in scores.items()},
            "overlay": OVERLAY[mode]}


def overlay_for(text: str, prev: List[str] | None = None) -> str:
    r = read(text, prev)
    return ("\n（这一轮他的状态：%s）\n" % r["overlay"]) if r["overlay"] else ""
