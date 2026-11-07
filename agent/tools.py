"""手：它能对这台电脑做的动作。

每个工具都是一个普通的 Python 函数，外面套一层说明（给模型看）。加一个新
能力 = 写一个函数 + 写一段说明，别的地方不用动。

安全这件事写在最前面：模型会自己决定调哪个工具、传什么参数，所以
  * 不许拼字符串进 shell
  * 命令只认白名单，别的直接拒
  * 路径都落在固定目录里
一个"助手"如果能把任意命令跑起来，那它就不是助手，是后门。
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import subprocess
from dataclasses import dataclass
from typing import Callable, Dict, List

HOME = os.path.expanduser("~")
# 数据放在项目自己的 data/ 里，不散落在主目录：
# 整个文件夹拷到机器人上，记忆跟着走。
WORKDIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
SHOTDIR = os.path.join(WORKDIR, "shots")
NOTES = os.path.join(WORKDIR, "notes.json")

SHELL_ALLOW = {"ls", "date", "df", "du", "pwd", "whoami", "uname", "sw_vers", "sysctl", "ps"}
SHELL_FORBID = (";", "|", "&", ">", "<", "`", "$(", "\n")


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    fn: Callable[..., str]


TOOLS: Dict[str, Tool] = {}

_MEMORY = None  # 由 main 在启动时绑定
_PROMISES = None
_ALARMS = None
_CFG = None
_SKILLS = None
_GATE = None


def bind_memory(mem) -> None:
    global _MEMORY
    _MEMORY = mem


def bind_promises(pr) -> None:
    global _PROMISES
    _PROMISES = pr


def bind_gate(gate) -> None:
    global _GATE
    _GATE = gate


def bind_skills(path) -> None:
    global _SKILLS
    _SKILLS = path


def bind_config(cfg) -> None:
    global _CFG
    _CFG = cfg


def bind_alarms(al) -> None:
    global _ALARMS
    _ALARMS = al


def tool(name: str, description: str, parameters: dict):
    def deco(fn):
        TOOLS[name] = Tool(name=name, description=description, parameters=parameters, fn=fn)
        return fn

    return deco


def _ensure_dirs():
    os.makedirs(SHOTDIR, exist_ok=True)


# ------------------------------------------------------------------ 工具们
@tool(
    "get_time",
    "查当前的日期和时间。用户问几点、今天几号、星期几时用它。",
    {"type": "object", "properties": {}, "required": []},
)
def get_time() -> str:
    now = _dt.datetime.now()
    week = "一二三四五六日"[now.weekday()]
    return now.strftime("%Y-%m-%d %H:%M") + " 星期" + week


APP_ALIAS = {
    "计算器": "Calculator", "备忘录": "Notes", "日历": "Calendar", "音乐": "Music",
    "访达": "Finder", "浏览器": "Safari", "微信": "WeChat", "终端": "Terminal",
    "地图": "Maps", "邮件": "Mail", "提醒事项": "Reminders", "照片": "Photos",
    "天气": "Weather", "设置": "System Settings", "系统设置": "System Settings",
    "活动监视器": "Activity Monitor", "文本编辑": "TextEdit", "预览": "Preview",
}


@tool(
    "open_app",
    "在这台 Mac 上打开一个应用程序。参数是应用名，比如「Safari」「备忘录」「计算器」「访达」。",
    {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "应用程序名称，中文英文都行"}
        },
        "required": ["name"],
    },
)
def open_app(name: str) -> str:
    name = (name or "").strip()
    name = APP_ALIAS.get(name, name)
    if not name or len(name) > 40:
        return "应用名不对。"
    if any(ch in name for ch in SHELL_FORBID):
        return "应用名里有不该有的符号，拒绝执行。"
    try:
        r = subprocess.run(["open", "-a", name], capture_output=True, timeout=10)
    except subprocess.TimeoutExpired:
        return "打开「%s」超时。" % name
    if r.returncode != 0:
        err = (r.stderr or b"").decode("utf-8", "ignore").strip()
        return "没打开「%s」。系统说：%s" % (name, err[:120] or "找不到这个应用")
    return "已经打开「%s」。" % name


@tool(
    "screenshot",
    "给整个屏幕截一张图，返回文件路径。用户让你看一下屏幕、或者帮你截图时用它。",
    {"type": "object", "properties": {}, "required": []},
)
def screenshot() -> str:
    _ensure_dirs()
    path = os.path.join(SHOTDIR, _dt.datetime.now().strftime("shot_%H%M%S.png"))
    try:
        r = subprocess.run(["screencapture", "-x", path], capture_output=True, timeout=15)
    except subprocess.TimeoutExpired:
        return "截图超时。"
    if r.returncode != 0 or not os.path.exists(path):
        return "截图失败。可能需要在「系统设置 → 隐私与安全性 → 屏幕录制」里授权。"
    return "截图存好了：%s" % path


@tool(
    "system_status",
    "查磁盘空间和电池电量。用户问「还剩多少电」「空间够不够」时用它。",
    {"type": "object", "properties": {}, "required": []},
)
def system_status() -> str:
    out = []
    try:
        d = subprocess.run(["df", "-h", "/"], capture_output=True, timeout=5, text=True)
        line = d.stdout.strip().splitlines()[-1].split()
        if len(line) >= 4:
            out.append("磁盘剩 %s，用了 %s" % (line[3], line[4]))
    except Exception:  # noqa: BLE001
        pass
    try:
        b = subprocess.run(["pmset", "-g", "batt"], capture_output=True, timeout=5, text=True)
        for token in b.stdout.replace(";", " ").split():
            if token.endswith("%"):
                out.append("电量 %s" % token)
                break
    except Exception:  # noqa: BLE001
        pass
    return "；".join(out) if out else "查不到系统状态。"


@tool(
    "remember",
    "把一件事记下来，以后能想起来。用户说「记住…」的时候用它。",
    {
        "type": "object",
        "properties": {"text": {"type": "string", "description": "要记住的内容"}},
        "required": ["text"],
    },
)
def remember(text: str) -> str:
    _ensure_dirs()
    items = []
    if os.path.exists(NOTES):
        try:
            with open(NOTES, encoding="utf-8") as fh:
                items = json.load(fh)
        except Exception:  # noqa: BLE001
            items = []
    items.append({"t": _dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "text": text})
    with open(NOTES, "w", encoding="utf-8") as fh:
        json.dump(items[-200:], fh, ensure_ascii=False, indent=1)
    return "记住了：%s" % text


@tool(
    "recall",
    "翻出以前记下的东西。用户问「我之前说过什么」「你还记得吗」时用它。",
    {
        "type": "object",
        "properties": {"keyword": {"type": "string", "description": "关键词，空着就全翻出来"}},
        "required": [],
    },
)
def recall(keyword: str = "") -> str:
    if not os.path.exists(NOTES):
        return "还没记过任何东西。"
    try:
        with open(NOTES, encoding="utf-8") as fh:
            items = json.load(fh)
    except Exception:  # noqa: BLE001
        return "记录文件坏了。"
    if keyword:
        items = [i for i in items if keyword in i.get("text", "")]
    if not items:
        return "没找到相关的记录。"
    return "\n".join("- %s：%s" % (i.get("t", "?"), i.get("text", "")) for i in items[-10:])


@tool(
    "run_shell",
    "跑一条只读的系统命令（ls/date/df/pwd/whoami/uname 等）。别的命令一律会被拒绝。",
    {
        "type": "object",
        "properties": {"command": {"type": "string", "description": "要执行的命令"}},
        "required": ["command"],
    },
)
def run_shell(command: str) -> str:
    command = (command or "").strip()
    if not command:
        return "命令是空的。"
    if any(bad in command for bad in SHELL_FORBID):
        return "命令里有管道、重定向之类的符号，为了安全拒绝执行。"
    head = command.split()[0]
    if head not in SHELL_ALLOW:
        return "「%s」不在白名单里。只能跑这些：%s" % (head, "、".join(sorted(SHELL_ALLOW)))
    try:
        r = subprocess.run(
            command.split(), capture_output=True, timeout=10, text=True, cwd=HOME
        )
    except subprocess.TimeoutExpired:
        return "命令超时。"
    out = (r.stdout or "")[:1500]
    err = (r.stderr or "")[:300]
    return (out + ("\n[错误] " + err if err.strip() else "")).strip() or "（没有输出）"



@tool(
    "look_around",
    "用摄像头看一眼：现在有几个人、有没有人在看着你、离得近不近。用户问「你看得见我吗」「现在有人吗」时用它。",
    {"type": "object", "properties": {}, "required": []},
)
def look_around() -> str:
    from . import eyes

    ok, why = eyes.available()
    if not ok:
        return "眼睛还没装好：%s" % why
    try:
        return eyes.Eye().look()["text"]
    except Exception as e:  # noqa: BLE001
        return "看不了：%s" % e


@tool(
    "set_volume",
    "设置系统音量。用户说「声音小一点」「调到 30」时用它。level 是 0 到 100。",
    {
        "type": "object",
        "properties": {"level": {"type": "integer", "description": "0-100"}},
        "required": ["level"],
    },
)
def set_volume(level: int) -> str:
    try:
        level = max(0, min(100, int(level)))
    except (TypeError, ValueError):
        return "音量要一个 0 到 100 的数字。"
    r = subprocess.run(
        ["osascript", "-e", "set volume output volume %d" % level],
        capture_output=True,
        timeout=10,
    )
    if r.returncode != 0:
        return "调不动音量：%s" % (r.stderr or b"").decode("utf-8", "ignore")[:100]
    return "音量已经调到 %d。" % level


@tool(
    "notify",
    "在屏幕右上角弹一条系统通知。用户说「提醒我…」时用它。",
    {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "标题"},
            "body": {"type": "string", "description": "内容"},
        },
        "required": ["title", "body"],
    },
)
def notify(title: str, body: str) -> str:
    script = 'display notification "%s" with title "%s"' % (
        (body or "").replace('"', "'")[:200],
        (title or "汤圆").replace('"', "'")[:60],
    )
    r = subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10)
    if r.returncode != 0:
        return "通知没弹出来：%s" % (r.stderr or b"").decode("utf-8", "ignore")[:100]
    return "通知已经弹出来了。"


@tool(
    "open_url",
    "用默认浏览器打开一个网址。只接受 http/https。",
    {
        "type": "object",
        "properties": {"url": {"type": "string", "description": "完整网址"}},
        "required": ["url"],
    },
)
def open_url(url: str) -> str:
    url = (url or "").strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        return "只开 http/https 开头的网址。"
    r = subprocess.run(["open", url], capture_output=True, timeout=10)
    if r.returncode != 0:
        return "打不开：%s" % url
    return "打开了 %s" % url


@tool(
    "list_files",
    "列出一个文件夹里有什么。默认看桌面。用户问「我桌面上有什么」时用它。",
    {
        "type": "object",
        "properties": {"dir": {"type": "string", "description": "文件夹路径，空着就是桌面"}},
        "required": [],
    },
)
def list_files(dir: str = "") -> str:  # noqa: A002
    path = dir.strip() or os.path.join(HOME, "Desktop")
    path = os.path.expanduser(path)
    if not os.path.isdir(path):
        return "没有这个文件夹：%s" % path
    try:
        names = sorted(os.listdir(path))[:40]
    except OSError as e:
        return "打不开这个文件夹：%s" % e
    if not names:
        return "这个文件夹是空的。"
    return "%s 里有 %d 样东西：%s" % (path, len(names), "、".join(names))



@tool(
    "remember_fact",
    "把一个关于用户的事实长期记下来（跨对话有效）。比如名字、城市、在做的项目、"
    "喜欢的口味。key 用短词（如「名字」「城市」「正在做」），value 一句话。",
    {
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "短标签，例如 名字 / 城市 / 正在做"},
            "value": {"type": "string", "description": "一句话事实"},
        },
        "required": ["key", "value"],
    },
)
def remember_fact(key: str, value: str) -> str:
    if _MEMORY is None:
        return "记忆还没接上。"
    return _MEMORY.set(key, value)


@tool(
    "forget_fact",
    "忘掉一条长期记忆。用户说「别记这个了」时用它。",
    {
        "type": "object",
        "properties": {"key": {"type": "string", "description": "要忘掉的标签"}},
        "required": ["key"],
    },
)
def forget_fact(key: str) -> str:
    if _MEMORY is None:
        return "记忆还没接上。"
    return _MEMORY.drop(key)


@tool(
    "recall_facts",
    "翻一遍长期记忆。用户问「你记得我什么」时用它。",
    {
        "type": "object",
        "properties": {"keyword": {"type": "string", "description": "关键词，空着就全翻"}},
        "required": [],
    },
)
def recall_facts(keyword: str = "") -> str:
    if _MEMORY is None:
        return "记忆还没接上。"
    items = _MEMORY.search(keyword)
    if not items:
        return "这条没记过。"
    return "\n".join(items[:20])



@tool(
    "read_clipboard",
    "读用户剪贴板里的内容。用户说「看看我复制的东西」时用它。",
    {"type": "object", "properties": {}, "required": []},
)
def read_clipboard() -> str:
    try:
        r = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=5)
    except Exception as e:  # noqa: BLE001
        return "读不到剪贴板：%s" % e
    text = (r.stdout or "").strip()
    if not text:
        return "剪贴板是空的。"
    if len(text) > 1200:
        return text[:1200] + "…（后面还有，太长了）"
    return text


@tool(
    "write_clipboard",
    "把一段文字放进剪贴板，用户可以直接粘贴。",
    {
        "type": "object",
        "properties": {"text": {"type": "string", "description": "要放进去的文字"}},
        "required": ["text"],
    },
)
def write_clipboard(text: str) -> str:
    if not text:
        return "内容是空的。"
    r = subprocess.run(["pbcopy"], input=text, text=True, timeout=5)
    if r.returncode != 0:
        return "写不进剪贴板。"
    return "已经放进剪贴板了，%d 个字。" % len(text)


@tool(
    "frontmost_app",
    "查用户现在正在用哪个应用、窗口标题是什么。用户问「我在干嘛」时用它。",
    {"type": "object", "properties": {}, "required": []},
)
def frontmost_app() -> str:
    script = (
        'tell application "System Events" to tell (first application process whose frontmost is true) '
        'to return name & " | " & (name of front window)'
    )
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
    except Exception as e:  # noqa: BLE001
        return "查不到：%s" % e
    if r.returncode != 0:
        return "查不到（可能需要在「隐私与安全性 → 辅助功能」里给终端授权）。"
    parts = [p.strip() for p in r.stdout.strip().split("|")]
    if len(parts) == 2:
        return "正在用 %s，窗口是「%s」。" % (parts[0], parts[1])
    return "正在用 %s。" % (parts[0] or "?")


@tool(
    "control_music",
    "控制音乐播放。action 只能是 playpause / next / previous。",
    {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["playpause", "next", "previous"]}
        },
        "required": ["action"],
    },
)
def control_music(action: str) -> str:
    cmd = {"playpause": "playpause", "next": "next track", "previous": "previous track"}.get(
        action or "", ""
    )
    if not cmd:
        return "只能 playpause / next / previous。"
    r = subprocess.run(
        ["osascript", "-e", 'tell application "Music" to %s' % cmd],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if r.returncode != 0:
        return "控制不了音乐：%s" % (r.stderr or "")[:80]
    return {"playpause": "已切换播放状态。", "next": "下一首。", "previous": "上一首。"}[action]


@tool(
    "lock_screen",
    "锁屏。用户说「我要走了」「锁一下」时用它。",
    {"type": "object", "properties": {}, "required": []},
)
def lock_screen() -> str:
    r = subprocess.run(
        ["osascript", "-e", 'tell application "System Events" to keystroke "q" using {control down, command down}'],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if r.returncode != 0:
        return "锁不了屏（需要「辅助功能」权限）。"
    return "锁了。"



@tool(
    "make_appointment",
    "记下一件约定：某天要问用户一件事。用户说「我明天要面试」「后天提醒我」时用它。"
    "due 必须是 YYYY-MM-DD，先调 get_time 弄清楚今天几号再算。",
    {
        "type": "object",
        "properties": {
            "what": {"type": "string", "description": "到那天要问什么，例如「面试」"},
            "due": {"type": "string", "description": "哪一天，YYYY-MM-DD"},
        },
        "required": ["what", "due"],
    },
)
def make_appointment(what: str, due: str) -> str:
    if _PROMISES is None:
        return "约会簿还没接上。"
    return _PROMISES.add(what, due)


@tool(
    "list_appointments",
    "看看记了哪些还没问的事。",
    {"type": "object", "properties": {}, "required": []},
)
def list_appointments() -> str:
    if _PROMISES is None:
        return "约会簿还没接上。"
    items = _PROMISES.pending()
    if not items:
        return "没有记着的事。"
    return "\n".join("%d. %s（%s）" % (i, x["what"], x["due"]) for i, x in enumerate(items))


@tool(
    "complete_appointment",
    "把第 N 条约定标成已经问过了。问完用户之后调它。",
    {
        "type": "object",
        "properties": {"index": {"type": "integer", "description": "从 0 开始"}},
        "required": ["index"],
    },
)
def complete_appointment(index: int) -> str:
    if _PROMISES is None:
        return "约会簿还没接上。"
    return _PROMISES.done(int(index))


@tool(
    "remember_sensitive",
    "记下一件敏感的事：你知道，但以后绝不主动提。用户说不开心的事、家里的变故、身体的毛病时用它。",
    {
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "短标签"},
            "value": {"type": "string", "description": "一句话"},
        },
        "required": ["key", "value"],
    },
)
def remember_sensitive(key: str, value: str) -> str:
    if _MEMORY is None:
        return "记忆还没接上。"
    return _MEMORY.set_private(key, value)



@tool(
    "write_note",
    "在备忘录里写一条（会真的写进「备忘录」App）。用户说「帮我记一下」「写个备忘录」时用它。",
    {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "标题，短"},
            "body": {"type": "string", "description": "正文"},
        },
        "required": ["title", "body"],
    },
)
def write_note(title: str, body: str) -> str:
    title = (title or "随手记").strip()[:60]
    safe_title = title.replace('"', "'")
    safe_body = (body or "").replace('"', "'")[:4000]
    script = (
        'tell application "Notes" to make new note with properties '
        '{name:"%s", body:"%s"}' % (safe_title, safe_body)
    )
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=15)
    if r.returncode == 0:
        return "写进备忘录了：《%s》。" % title

    # 备忘录写不进去（没授权）就存成文件，别把话吞了
    d = os.path.join(WORKDIR, "notes")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, _dt.datetime.now().strftime("%Y%m%d_%H%M_") + safe_title + ".md")
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("# %s\n\n%s\n" % (title, body))
    except OSError as e:
        return "备忘录没写进去：%s" % e
    return "备忘录 App 没授权，先存成文件了：%s" % path


@tool(
    "set_alarm",
    "设一个闹钟，到点她会叫你。when 可以是 2026-11-06 15:30、07:30，或相对时间（用 set_timer 更简单）。",
    {
        "type": "object",
        "properties": {
            "when": {"type": "string", "description": "什么时候"},
            "what": {"type": "string", "description": "叫你干嘛"},
        },
        "required": ["when", "what"],
    },
)
def set_alarm(when: str, what: str) -> str:
    if _ALARMS is None:
        return "闹钟还没接上。"
    return _ALARMS.add(when, what)


@tool(
    "set_timer",
    "设几分钟后的提醒。用户说「十分钟后提醒我」时用它。",
    {
        "type": "object",
        "properties": {
            "minutes": {"type": "number", "description": "多少分钟后，可以是小数"},
            "what": {"type": "string", "description": "提醒什么"},
        },
        "required": ["minutes", "what"],
    },
)
def set_timer(minutes: float, what: str) -> str:
    if _ALARMS is None:
        return "闹钟还没接上。"
    from .alarms import in_minutes

    try:
        mins = float(minutes)
    except (TypeError, ValueError):
        return "分钟数不对。"
    if not (0 < mins <= 60 * 24 * 7):
        return "时间要大于 0，且不超过一周。"
    return _ALARMS.add(in_minutes(mins), what)


@tool(
    "list_alarms",
    "看看设了哪些闹钟。",
    {"type": "object", "properties": {}, "required": []},
)
def list_alarms() -> str:
    if _ALARMS is None:
        return "闹钟还没接上。"
    return _ALARMS.list_text()


@tool(
    "cancel_alarm",
    "取消第 N 个闹钟（编号从 list_alarms 里看）。",
    {
        "type": "object",
        "properties": {"index": {"type": "integer", "description": "从 0 开始"}},
        "required": ["index"],
    },
)
def cancel_alarm(index: int) -> str:
    if _ALARMS is None:
        return "闹钟还没接上。"
    return _ALARMS.cancel(int(index))



@tool(
    "look_at_screen",
    "看一眼用户当前的屏幕，然后回答关于它的问题。用户说「你看一下我的屏幕」「这个怎么弄」时用它。",
    {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "要看什么、回答什么"}
        },
        "required": ["question"],
    },
)
def look_at_screen(question: str) -> str:
    if _CFG is None:
        return "配置还没接上。"
    from . import vision

    ok, why = vision.available(_CFG)
    if not ok:
        return why

    path = os.path.join(SHOTDIR, _dt.datetime.now().strftime("screen_%H%M%S.jpg"))
    _ensure_dirs()
    r = subprocess.run(["screencapture", "-x", "-t", "jpg", path], capture_output=True, timeout=20)
    if r.returncode != 0 or not os.path.exists(path):
        return "截不了屏。去「系统设置 → 隐私与安全性 → 屏幕录制」给终端授权。"
    try:
        return vision.ask_about(_CFG, path, question)
    except Exception as e:  # noqa: BLE001
        return "看图失败了：%s" % e



@tool(
    "read_skill",
    "读一份技能资料。比如三观访谈要出题时：read_skill(\"worldview\", \"references/question-bank.md\")。"
    "默认读 SKILL.md。",
    {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "技能名，如 worldview / love / memory"},
            "file": {"type": "string", "description": "技能目录里的文件名，默认 SKILL.md"},
        },
        "required": ["name"],
    },
)
def read_skill(name: str, file: str = "SKILL.md") -> str:
    if not _SKILLS:
        return "技能目录还没接上。"
    name = (name or "").strip()
    file = (file or "SKILL.md").strip()
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", name) or ".." in file or file.startswith("/"):
        return "名字不合法。"
    path = os.path.join(_SKILLS, name, file)
    if not os.path.isfile(path):
        return "没有这个文件：%s/%s" % (name, file)
    try:
        text = open(path, encoding="utf-8").read()
    except OSError as e:
        return "读不了：%s" % e
    if len(text) > 9000:
        return text[:9000] + "\n\n（后面还很长，先看这些）"
    return text


# ------------------------------------------------------------------ 给模型
def schemas() -> List[dict]:
    return [
        {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
        for t in TOOLS.values()
    ]


def execute(name: str, arguments: str) -> str:
    """执行一个工具调用，永远返回字符串（出错也返回字符串，好让模型自己救场）。"""
    if _GATE is not None and not _GATE.allow(name):
        return (
            "被你拦下了：这个人没叫过你的名字，不能替他动电脑。"
            "如果他确实是主人，让他先叫你一声。"
        )
    t = TOOLS.get(name)
    if t is None:
        return "没有这个工具：%s" % name
    try:
        args = json.loads(arguments) if arguments and arguments.strip() else {}
    except json.JSONDecodeError:
        return "参数不是合法 JSON：%s" % arguments[:200]
    if not isinstance(args, dict):
        return "参数应该是一个对象。"
    try:
        return str(t.fn(**args))
    except TypeError as e:
        return "参数不对：%s" % e
    except Exception as e:  # noqa: BLE001
        return "工具「%s」出错：%s: %s" % (name, type(e).__name__, e)
