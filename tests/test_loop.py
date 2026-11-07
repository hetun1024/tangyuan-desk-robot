#!/usr/bin/env python3
"""思考循环的单元测试。假的"大脑"，不发网络请求。

这个测试跑的是最危险的部分：模型乱调工具、工具报错、模型绕圈不出结果。
这几种情况在真机演示时一定会碰到，所以必须先在测试里见到它们。

    python3 tests/test_loop.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.brain import BrainError  # noqa: E402
from agent.config import Config  # noqa: E402
from agent.loop import Agent  # noqa: E402


class FakeBrain:
    """按剧本回复。剧本用完就返回一句废话。"""

    def __init__(self, script=None, fail_at=None):
        self.script = list(script or [])
        self.requests = []
        self.fail_at = fail_at

    def chat(self, messages, tools=None, temperature=0.3):
        self.requests.append(list(messages))
        if self.fail_at is not None and len(self.requests) - 1 == self.fail_at:
            raise BrainError("网络断了")
        if not self.script:
            return {"content": "（没剧本了）", "tool_calls": []}
        return self.script.pop(0)


def call(name, args="{}", cid="c1"):
    return {"id": cid, "type": "function", "function": {"name": name, "arguments": args}}


def test_直接回答不调工具():
    brain = FakeBrain([{"content": "我在。", "tool_calls": []}])
    agent = Agent(brain, Config())
    assert agent.ask("在吗") == "我在。"
    assert len(brain.requests) == 1


def test_调一次工具再回答():
    brain = FakeBrain(
        [
            {"content": "", "tool_calls": [call("get_time")]},
            {"content": "现在我知道了。", "tool_calls": []},
        ]
    )
    agent = Agent(brain, Config())
    reply = agent.ask("现在几点")
    assert reply == "现在我知道了。"
    # 第二次请求里，应该能看到工具返回的内容
    second = brain.requests[1]
    tool_msgs = [m for m in second if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert "星期" in tool_msgs[0]["content"], tool_msgs[0]["content"]


def test_工具名写错时把错误喂回给模型():
    brain = FakeBrain(
        [
            {"content": "", "tool_calls": [call("open_rocket")]},
            {"content": "这个我做不到。", "tool_calls": []},
        ]
    )
    agent = Agent(brain, Config())
    assert agent.ask("发射火箭") == "这个我做不到。"
    tool_msg = [m for m in brain.requests[1] if m.get("role") == "tool"][0]
    assert "没有这个工具" in tool_msg["content"]


def test_参数不是_json_也不会崩():
    brain = FakeBrain(
        [
            {"content": "", "tool_calls": [call("get_time", "{坏掉的参数")]},
            {"content": "嗯，出错了。", "tool_calls": []},
        ]
    )
    agent = Agent(brain, Config())
    assert agent.ask("试试") == "嗯，出错了。"
    tool_msg = [m for m in brain.requests[1] if m.get("role") == "tool"][0]
    assert "不是合法 JSON" in tool_msg["content"]


def test_模型绕圈会被拦住():
    loop = [{"content": "", "tool_calls": [call("get_time", "{}", "c%d" % i)]} for i in range(10)]
    brain = FakeBrain(loop)
    agent = Agent(brain, Config(max_steps=3))
    reply = agent.ask("一直查时间")
    assert "绕" in reply, reply
    assert len(brain.requests) == 3, "应该在 max_steps 次之后停下"


def test_网络出错时把用户那句话撤回():
    brain = FakeBrain([{"content": "x", "tool_calls": []}], fail_at=0)
    agent = Agent(brain, Config())
    try:
        agent.ask("你好")
        raise AssertionError("应该抛 BrainError")
    except BrainError:
        pass
    roles = [m["role"] for m in agent.history]
    assert roles == ["system"], "失败后历史里不该留下半句用户输入：%s" % roles


def test_短对话不会被裁剪():
    """闲聊几句不该触发裁剪 —— 以前按条数裁，四轮就把开头砍了。"""
    brain = FakeBrain([{"content": "好", "tool_calls": []} for _ in range(40)])
    agent = Agent(brain, Config())
    for i in range(20):
        agent.ask("第 %d 句" % i)
    assert agent.history[0]["role"] == "system"
    assert len(agent.history) == 41, len(agent.history)
    assert agent.summary == ""


def test_长内容会按字符预算裁剪并留下摘要():
    """一次看屏幕可能两千字，它会把你刚说的话挤掉 —— 所以要按字符算。"""
    brain = FakeBrain(
        [{"content": "屏幕内容：" + "这是一段很长的屏幕文字。" * 100, "tool_calls": []} for _ in range(20)]
    )
    agent = Agent(brain, Config())
    for i in range(20):
        agent.ask("第 %d 句" % i)
    total = sum(len(str(m.get("content") or "")) for m in agent.history)
    assert total <= 14000, total
    assert agent.summary, "裁掉的东西必须进摘要，不能凭空消失"
    assert agent.history[0]["role"] == "system"
    assert agent.history[1]["role"] == "user", "历史不该以她自己的话开头"


def test_摘要会进系统提示():
    brain = FakeBrain([{"content": "好", "tool_calls": []}])
    agent = Agent(brain, Config())
    agent.summary = "他：我在做机器人；你：听起来不错"
    agent._refresh_system()
    assert "我在做机器人" in agent.history[0]["content"]


def test_同一个工具连续失败两次就停():
    """真实场景：用户把一条终端命令粘给了她，她拼命重试 run_shell。"""
    script = [
        {"content": "", "tool_calls": [call("run_shell", '{"command": "curl x"}', "c1")]},
        {"content": "", "tool_calls": [call("run_shell", '{"command": "ps aux"}', "c2")]},
        {"content": "", "tool_calls": [call("run_shell", '{"command": "ls"}', "c3")]},
    ]
    brain = FakeBrain(script)
    agent = Agent(brain, Config(max_steps=5))
    reply = agent.ask("cd ~/Downloads && python3 face.py")
    assert "两次都没成" in reply, reply
    assert len(brain.requests) == 2, "不该把 max_steps 全烧完，实际请求 %d 次" % len(brain.requests)


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in tests:
        try:
            fn()
            print("ok    %s" % fn.__name__)
        except AssertionError as e:
            failed += 1
            print("FAIL  %s: %s" % (fn.__name__, e))
        except Exception as e:  # noqa: BLE001
            failed += 1
            print("ERROR %s: %s: %s" % (fn.__name__, type(e).__name__, e))
    print("\n%d/%d passed" % (len(tests) - failed, len(tests)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
