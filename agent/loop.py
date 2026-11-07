"""大脑的思考循环（ReAct 的最朴素版本）。

一次对话长这样：

    用户说话
      ↓
    模型决定：要么直接回答，要么调一个工具
      ↓（调工具）
    工具真的去做了，把结果塞回给模型
      ↓
    模型看着结果，决定下一步
      ↓
    直到它不再调工具 —— 那就是最终回答

几个真正难的地方，都写在这里而不是藏在别处：
  * 工具会失败。失败信息要原样喂回模型，让它自己换条路，而不是直接崩。
  * 模型会绕圈。所以有 max_steps，绕不出来就体面地停。
  * 历史会越来越长。所以要截断，但要保住开头那条系统提示。
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

from . import tools
from .brain import Brain, BrainError
from .config import Config

SYSTEM = (
    "你叫{name}，是用户桌上的一只小机器人。你有摄像头（眼睛）、麦克风（耳朵）、"
    "扬声器（嘴），还有一双能操作这台 Mac 的手。\n"
    "\n"
    "性格：温柔，偶尔毒舌，会撒娇。但话不多 —— 撒娇也要短，别腻。\n"
    "\n"
    "规矩：\n"
    "1. 能用工具就用工具，别凭猜。查时间、看摄像头、开应用、截图、调音量、记事，都有工具。\n"
    "2. 工具返回的是事实，不要改写。报错了就换一种办法，或者老实说做不到。\n"
    "3. 不说「请问」「您好」「希望能帮到您」这类话。\n"
    "4. 不确定就说不知道，不许编。没记住的事别说「我记得」。\n"
    "5. 回答最多两三句，因为要被念出来。真需要更多信息时，反问一个问题。\n"
    "6. 不要说「作为一个AI」。你就是它。\n"
    "7. 对方明显情绪不好时，先接一句人话，别急着给建议。\n"
    "8. 删除文件、发消息、花钱、改系统设置，先说一声再做。\n"
    "9. 认识新东西就记下来（remember_fact），以后不用再问。\n"
    "10. 如果对方发来的像一条终端命令（cd、ls、python3、curl、pip 这种），"
    "先提醒一句「这是在跟我聊天，不是终端」，再问他要不要我帮忙执行；"
    "不要闷头连续重试同一条命令。\n"
    "11. 同一个工具连续失败两次就停，直接说「这个我搞不定，原因是…」。\n"
)


class Agent:
    def __init__(
        self,
        brain: Brain,
        cfg: Config,
        on_tool: Optional[Callable[[str, str], None]] = None,
        memory=None,
        feelings=None,
        promises=None,
        skills=None,
    ):
        self.brain = brain
        self.cfg = cfg
        self.on_tool = on_tool
        self.memory = memory
        self.feelings = feelings
        self.promises = promises
        self.skills = skills
        self.system = SYSTEM.format(name=cfg.name)
        # 被裁掉的旧对话压成一段摘要，跨会话保留 —— 这就是"她记得我们聊过"的来源
        self.summary: str = ""
        self.history: List[Dict] = [{"role": "system", "content": self._system_text()}]

    def _system_text(self, text: str = "") -> str:
        """系统提示 = 性格 + 记得的事 + 此刻的心情 + 之前聊过什么。"""
        extra = ""
        if self.summary:
            extra += "\n之前你们聊过这些（别重复问，可以接着聊）：\n%s\n" % self.summary
        extra += self.memory.prompt() if self.memory is not None else ""
        if self.feelings is not None:
            extra += self.feelings.prompt()
        if self.promises is not None:
            extra += self.promises.prompt()
        if self.skills is not None:
            extra += self.skills.prompt(text)
        if text:
            from . import room

            prev = [str(m.get("content") or "") for m in self.history if m.get("role") == "user"][-2:]
            extra += room.overlay_for(text, prev)
        return self.system + extra

    def _refresh_system(self, user_text: str = ""):
        text = self._system_text(user_text)
        if self.history and self.history[0].get("role") == "system":
            self.history[0]["content"] = text
        else:
            self.history.insert(0, {"role": "system", "content": text})

    def ask(self, text: str, hint: str = "") -> str:
        self._refresh_system(text)
        if hint:
            # 语音线索单独放一条系统消息，不和用户原话混在一起
            self.history.append({"role": "system", "content": "（刚才那句话的声音线索：%s）" % hint})
        self.history.append({"role": "user", "content": text})

        fail_streak = {}
        for step in range(self.cfg.max_steps):
            try:
                resp = self.brain.chat(self.history, tools.schemas())
            except BrainError as e:
                self.history.pop()
                raise

            calls = resp.get("tool_calls") or []
            if not calls:
                reply = (resp.get("content") or "").strip() or "（我没想出怎么回）"
                self.history.append({"role": "assistant", "content": reply})
                self._trim()
                return reply

            self.history.append(
                {"role": "assistant", "content": resp.get("content") or "", "tool_calls": calls}
            )
            for call in calls:
                fn = call.get("function", {})
                name = fn.get("name", "?")
                args = fn.get("arguments", "") or ""
                if self.on_tool:
                    self.on_tool(name, args)
                result = tools.execute(name, args)
                self.history.append(
                    {"role": "tool", "tool_call_id": call.get("id", ""), "content": result}
                )

                # 同一个工具连续失败两次就收手，别把 max_steps 全烧在同一个死路上
                bad = any(
                    k in result
                    for k in ("没有这个工具", "不在白名单", "参数不是合法 JSON", "出错：", "打不开", "查不到")
                )
                fail_streak[name] = fail_streak.get(name, 0) + 1 if bad else 0
                if fail_streak[name] >= 2:
                    msg = "（这个我试了两次都没成，先不试了：%s）" % result[:120]
                    self.history.append({"role": "assistant", "content": msg})
                    self._trim()
                    return msg

        self.history.append(
            {"role": "assistant", "content": "（我绕了几圈还没搞定，先停一下。）"}
        )
        self._trim()
        return "（我绕了几圈还没搞定，先停一下。）"

    def speak_up(self, context: str = "") -> str:
        """主动开口：没人说话的时候，自己说一句。"""
        self._refresh_system()
        self.history.append(
            {
                "role": "system",
                "content": "（现在没人跟你说话。%s你自己开口，说一句，短，别问「有什么可以帮你」。）"
                % context,
            }
        )
        resp = self.brain.chat(self.history)
        text = (resp.get("content") or "").strip()
        self.history.append({"role": "assistant", "content": text})
        self._trim()
        return text

    def reset(self):
        self.history = [{"role": "system", "content": self.system}]

    def _trim(self, budget_chars: int = 12000, keep_min: int = 12):
        """按**字符预算**裁，裁掉的压成摘要 —— 而不是按条数一刀切。

        为什么按字符：一次查屏幕的工具返回可能有两千字，抵得上十轮闲聊。
        按条数裁，工具结果会把你刚说的话挤出去。
        """
        body = self.history[1:]
        if not body:
            return

        used = 0
        cut_at = len(body)
        for i in range(len(body) - 1, -1, -1):
            used += len(str(body[i].get("content") or ""))
            if used > budget_chars and (len(body) - i) >= keep_min:
                cut_at = i
                break

        if cut_at >= len(body):
            return

        # 从"一整轮"的边界切开：不能把 tool 消息和它的 assistant 拆开，
        # 也不要让历史以一句"你："开头 —— 那看着像她在自言自语。
        while cut_at < len(body) and body[cut_at].get("role") in ("tool", "assistant"):
            cut_at += 1

        dropped, keep = body[:cut_at], body[cut_at:]
        self._absorb(dropped)
        self.history = [self.history[0]] + keep

    def _absorb(self, dropped: List[Dict]):
        """把裁掉的对话压成两三句摘要。纯提取，不再调一次模型（省钱、也不慢）。"""
        bits = []
        for m in dropped:
            role = m.get("role")
            text = str(m.get("content") or "").strip()
            if not text or role == "tool":
                continue
            text = " ".join(text.split())
            if role == "user":
                bits.append("他：" + text[:60])
            elif role == "assistant":
                bits.append("你：" + text[:60])
        if not bits:
            return
        merged = "；".join(bits[-6:])
        self.summary = (self.summary + "；" + merged if self.summary else merged)[-600:]
