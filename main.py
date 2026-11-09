#!/usr/bin/env python3
"""入口。

    python3 main.py                    # 打字对话
    python3 main.py --talk             # 语音对话（要麦克风）
    python3 main.py --check            # 只测 key 通不通
    python3 main.py --once "现在几点"    # 问一句就退
    python3 main.py --transcribe x.wav  # 只测耳朵
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import socket
import subprocess
import sys
import time

from agent.brain import Brain, BrainError
from agent.config import Config
from agent import vocables
from agent.gate import Gate
from agent.alarms import Alarms
from agent.feelings import Feelings
from agent.promises import Promises
from agent.loop import Agent
from agent.voice import available, speak

ROOT = os.path.dirname(os.path.abspath(__file__))
PROFILE = os.path.join(ROOT, "data", "profile.json")
FEELINGS = os.path.join(ROOT, "data", "feelings.json")
PROMISES = os.path.join(ROOT, "data", "promises.json")
ALARMS = os.path.join(ROOT, "data", "alarms.json")
SESSION = os.path.join(ROOT, "data", "session.json")

IDLE_BEFORE_SPEAKING_UP = 90.0  # 安静这么久，她才会自己开口
SPEAK_UP_COOLDOWN = 600.0  # 两次主动之间至少隔这么久


VOICE = vocables.Voice()
GATE = Gate()


def chirp(text: str, cfg: Config, feel: Feelings) -> None:
    """拟声词：很短，语速稍快一点，像随口应一声。"""
    speak(text, cfg.voice, enabled=True, rate=max(150, feel.voice_rate() + 10),
          pitch=cfg.pitch + feel.voice_pitch())


def hear(text: str) -> None:
    """先登记：这句话有没有叫她名字。"""
    ok = GATE.hear(text)
    if GATE.enabled and ok:
        left = GATE.remain()
        if left > 1:
            print("  ✓ 她认得这声（授权还剩 %.0f 秒）" % left)
    elif GATE.enabled:
        print("  ✗ 没叫名字，只聊天，不动手")


def react(text: str, cfg: Config, feel: Feelings) -> None:
    """先读一下他这句话里的情绪，该出声就出，再交给模型。"""
    kind = vocables.detect(text)
    if kind == "praise":
        feel.event("praise")
    elif kind == "sad":
        feel.event("user_low")
    elif kind == "tired":
        feel.event("user_low")
    said = VOICE.maybe(kind)
    if said:
        print("  ～ %s" % said)
        chirp(said, cfg, feel)


def on_tool(name, args_text):
    print("  🔧 %s %s" % (name, args_text[:90]))


def load_feelings() -> Feelings:
    feel = Feelings.load(FEELINGS)
    feel.start_session()
    return feel


FACE_PORT = 8770
FACE_URL = "http://127.0.0.1:%d" % FACE_PORT
_face_proc = None


def _face_alive() -> bool:
    try:
        socket.create_connection(("127.0.0.1", FACE_PORT), 0.3).close()
        return True
    except OSError:
        return False


def face_up(timeout: float = 5.0) -> bool:
    """把表情窗口拉起来。已经开着就直接用，没有就自己开一个。"""
    global _face_proc
    if _face_alive():
        return True
    try:
        _face_proc = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "face.py")],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:  # noqa: BLE001
        return False
    t0 = time.time()
    while time.time() - t0 < timeout:
        if _face_alive():
            return True
        time.sleep(0.15)
    return False


def face_down() -> None:
    """退出时把自己开的表情窗口关掉，别留孤儿进程。"""
    global _face_proc
    if _face_proc is not None:
        try:
            _face_proc.terminate()
        except Exception:  # noqa: BLE001
            pass
        _face_proc = None


MOOD_FILE = os.path.expanduser("~/.tangyuan_mood")


def _write_mood(emotion: str) -> None:
    """告诉桌面上的那个她：现在该是什么表情。

    桌面宠物是独立的原生窗口，不经过 Python，所以用一个文件传话。
    她没开的时候就没人读，写失败也无所谓。
    """
    try:
        with open(MOOD_FILE, "w", encoding="utf-8") as fh:
            fh.write(emotion)
    except OSError:
        pass


def _face(emotion: str) -> None:
    """改表情；表情窗口和桌面宠物都跟着变。"""
    import urllib.request

    _write_mood(emotion)
    try:
        urllib.request.urlopen(FACE_URL + "/emotion?name=" + emotion, timeout=0.5).read()
    except Exception:  # noqa: BLE001
        pass


def auto_face(feel: Feelings) -> str:
    """她的心情决定脸上是什么表情。"""
    if feel.energy < 0.30:
        return "sleepy"
    if feel.sulk:
        return "angry"
    if feel.valence > 0.40:
        return "love"
    if feel.valence > 0.15:
        return "happy"
    if feel.valence < -0.25:
        return "sad"
    return "idle"


def load_summary() -> str:
    """上次聊到哪儿了 —— 关掉程序再打开还接着聊，靠它。"""
    try:
        with open(SESSION, encoding="utf-8") as fh:
            return str(json.load(fh).get("summary") or "")
    except Exception:  # noqa: BLE001
        return ""


def save_summary(agent) -> None:
    try:
        os.makedirs(os.path.dirname(SESSION), exist_ok=True)
        with open(SESSION, "w", encoding="utf-8") as fh:
            json.dump({"summary": agent.summary, "saved": dt.datetime.now().isoformat(timespec="seconds")},
                      fh, ensure_ascii=False, indent=1)
    except Exception:  # noqa: BLE001
        pass


def make_agent(cfg: Config, feel: Feelings, pr: Promises, al: Alarms) -> Agent:
    from agent import tools
    from agent.memory import Memory

    from agent.skills import Library

    lib = Library(os.path.join(ROOT, "skills"))
    mem = Memory(PROFILE)
    tools.bind_memory(mem)
    tools.bind_promises(pr)
    tools.bind_alarms(al)
    tools.bind_config(cfg)
    tools.bind_skills(os.path.join(ROOT, "skills"))
    tools.bind_gate(GATE)
    agent = Agent(Brain(cfg), cfg, on_tool=on_tool, memory=mem, feelings=feel,
                  promises=pr, skills=lib)
    agent.summary = load_summary()
    return agent


def say(text: str, cfg: Config, feel: Feelings, enabled: bool = True) -> None:
    """她的声音由她的心情决定，不是固定的。"""
    speak(
        text,
        cfg.voice,
        enabled=enabled,
        rate=feel.voice_rate(),
        pitch=cfg.pitch + feel.voice_pitch(),
    )


def turn(agent: Agent, cfg: Config, feel: Feelings, speak_on: bool, text: str) -> None:
    hear(text)
    react(text, cfg, feel)
    _face("thinking")
    try:
        reply = agent.ask(text)
    except BrainError as e:
        _face(auto_face(feel))
        print("  ✗ %s" % e)
        return
    print("它> %s" % reply)
    feel.mark_spoke()
    feel.event("chat")  # 聊天本身是件好事，让她慢慢开心起来
    _face("talking")
    say(reply, cfg, feel, speak_on)
    _face(auto_face(feel))


def fire_alarms(al: Alarms, cfg: Config, feel: Feelings, say_fn) -> None:
    """到点的闹钟，直接念出来。"""
    for item in al.due():
        try:
            late = (
                dt.datetime.now() - dt.datetime.fromisoformat(item["at"])
            ).total_seconds() / 60.0
        except Exception:  # noqa: BLE001
            late = 0.0
        if late > 5:
            line = "呃，%s 的闹钟我刚才没赶上——%s。" % (item["at"][11:16], item["what"])
        else:
            line = "到点了，%s。" % item["what"]
        print("  ⏰ %s" % line)
        say_fn(line)
        feel.event("task_done", "闹钟响了")


def greeting(feel: Feelings, pr: Promises) -> str:
    """开场白分四种，看的是"隔了多久 + 心情 + 有没有欠着的事"。"""
    due = pr.due_today() + pr.overdue()
    if due:
        return "对了，今天你有个事——%s。怎么样？" % due[0]["what"]
    if feel.days_known in (7, 30, 100, 365):
        return "今天是认识第 %d 天。" % feel.days_known
    hour = dt.datetime.now().hour
    if (hour >= 23 or hour < 5) and feel.session_gap < 1:
        return "还没睡？"
    if feel.sulk:
        return "哦，你还知道回来。"
    hours = feel.session_gap
    if hours > 6:
        return "你回来了。"
    if hours > 1:
        return "又见面了。"
    if feel.mood_word in ("有点难过", "有点烦躁"):
        return "……嗯，我在。"
    return "我在。"


def proactive_context(feel: Feelings, pr: Promises, n: int) -> str:
    """她自己开口时说什么，按优先级排。"""
    due = pr.due_today() + pr.overdue()
    if due:
        return "有件事你一直想问他：%s。现在问。" % due[0]["what"]
    if n % 3 == 2:
        return "说一句你自己在想的事，跟用户没关系，短，别提问。"
    hours = feel.hours_since_seen()
    if hours > 3:
        return "你们已经 %.0f 小时没见了。" % hours
    hour = dt.datetime.now().hour
    if hour >= 23 or hour < 6:
        return "现在是深夜。"
    return ""


def run_text(agent: Agent, cfg: Config, feel: Feelings, speak_on: bool, al: Alarms) -> int:
    print("大脑已上线（%s）。敲 exit 退出。" % cfg.model)
    print("试试：现在几点 / 打开计算器 / 你看得见我吗 / 记住我叫小满")
    print()
    while True:
        try:
            text = input("你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text:
            continue
        if text.lower() in ("exit", "quit", "q", "退出"):
            break
        turn(agent, cfg, feel, speak_on, text)
        fire_alarms(al, cfg, feel, lambda t: say(t, cfg, feel, speak_on))
    feel.save()
    return 0


def run_talk(agent: Agent, cfg: Config, feel: Feelings, pr: Promises, al: Alarms) -> int:
    from agent import ears as ears_mod
    from agent.mood import Mood

    backend = cfg.asr
    ok, why = ears_mod.available(backend)
    if not ok:
        vosk_ok, _ = ears_mod.available("vosk")
        if backend == "whisper" and vosk_ok:
            print("   ⚠️  whisper 还没装好，先用 vosk 顶着（会更准不了多少，但能说话）。")
            print("      （原因：%s）" % why)
            backend = "vosk"
        else:
            print("耳朵还没装好：%s" % why)
            print('双击「启动大脑.command」会自动装；或者手动：')
            print('  python3 -m pip install --user -i '
                  'https://pypi.tuna.tsinghua.edu.cn/simple faster-whisper')
            return 2

    print("  识别引擎：%s" % (
        "whisper-" + cfg.whisper_size if backend == "whisper" else "vosk"))
    try:
        ears = ears_mod.Ears(backend=backend, whisper_size=cfg.whisper_size)
        ears._load()
    except FileNotFoundError as e:
        print(e)
        return 2
    except Exception as e:  # noqa: BLE001
        print("加载识别模型失败：%s" % e)
        return 2

    mood = Mood()

    print()
    print("  ⚠️  第一次会弹「允许访问麦克风」，点允许。")
    print("  直接说话，不用按键。Ctrl-C 退出。")
    print()
    try:
        ears.start()
    except RuntimeError as e:
        print(e)
        return 2

    say(greeting(feel, pr), cfg, feel)

    idle = 0.0
    last_spoke_up = time.monotonic()
    ignored_marked = False
    spoke_up = 0

    try:
        while True:
            try:
                text = ears.listen()
            except RuntimeError as e:
                print("  ✗ %s" % e)
                break

            fire_alarms(al, cfg, feel, lambda t: say(t, cfg, feel))

            if not text:
                _face("idle")
                idle += 8.0
                if idle > 600 and not ignored_marked:
                    feel.event("ignored", "安静了十分钟")
                    ignored_marked = True

                if idle > IDLE_BEFORE_SPEAKING_UP and time.monotonic() - last_spoke_up > SPEAK_UP_COOLDOWN:
                    spoke_up += 1
                    ctx = proactive_context(feel, pr, spoke_up)
                    try:
                        line = agent.speak_up(ctx)
                    except BrainError:
                        line = ""
                    if line:
                        print("它（自己开口）> %s" % line)
                        feel.mark_spoke()
                        say(line, cfg, feel)
                        last_spoke_up = time.monotonic()
                        idle = 0.0
                        ignored_marked = False
                continue

            idle = 0.0
            ignored_marked = False
            audio = getattr(ears, "last_audio", b"") or b""
            info = mood.read(audio)
            if info["mood"] in ("低落", "疲惫"):
                feel.event("user_low")  # 情绪会传染：你不高兴，她也安静下来
            elif info["mood"] == "有精神":
                feel.event("user_high")
            secs = len(audio) / 32000.0
            print("你> %s   〔%.1fs / %s / 她：%s〕" % (text, secs, info["mood"], feel.mood_word))

            hear(text)
            react(text, cfg, feel)
            _face("thinking")
            try:
                reply = agent.ask(text, hint=str(info["hint"]))
            except BrainError as e:
                print("  ✗ %s" % e)
                continue
            print("它> %s" % reply)
            feel.mark_spoke()
            feel.event("chat")
            _face("talking")
            say(reply, cfg, feel)
            _face(auto_face(feel))
    except KeyboardInterrupt:
        print("\n拜拜。")
    finally:
        ears.stop()
        feel.save()
        save_summary(agent)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="robot brain")
    ap.add_argument("--config", default=None, help="配置文件路径")
    ap.add_argument("--once", default=None, help="只问这一句")
    ap.add_argument("--talk", action="store_true", help="语音对话模式")
    ap.add_argument("--transcribe", default=None, help="只识别一个 wav 文件")
    ap.add_argument("--no-voice", action="store_true", help="回答不念出来")
    ap.add_argument("--check", action="store_true", help="只检查 key 和网络")
    ap.add_argument("--no-face", action="store_true", help="不开表情窗口")
    args = ap.parse_args(argv)

    cfg = Config.load(args.config)

    if args.transcribe:
        from agent import ears as ears_mod

        print(ears_mod.Ears(ears_mod.default_model_dir()).transcribe_wav(args.transcribe))
        return 0

    problem = cfg.check()
    if problem:
        print(problem)
        return 2

    if args.check:
        print("配置：%s  |  模型：%s" % (cfg.base_url, cfg.model))
        try:
            r = Brain(cfg).chat([{"role": "user", "content": "说两个字：你好"}])
            print("通了。它回：%s" % (r["content"] or "(空)"))
            print("音色：%s" % (cfg.voice if available() else "（这台机器没有 say）"))
            return 0
        except BrainError as e:
            print("不通：%s" % e)
            return 1

    GATE.wake = cfg.wake_word
    GATE.enabled = bool(cfg.require_wake and cfg.wake_word)
    feel = load_feelings()
    pr = Promises(PROMISES)
    al = Alarms(ALARMS)
    agent = make_agent(cfg, feel, pr, al)
    speak_on = (not args.no_voice) and available()

    print("她现在的状态：%s（熟 %d 天）" % (feel.mood_word, feel.streak_days))

    try:
        from agent import eyes as _eyes

        lux = _eyes.brightness()
        if lux is not None:
            if lux < 45:
                feel.event("dark")
                print("房间挺暗的（亮度 %.0f），她有点困。" % lux)
            else:
                print("房间亮度 %.0f。" % lux)
    except Exception:  # noqa: BLE001
        pass

    if not args.no_face:
        if face_up():
            print("表情窗口：已连上（启动自检：先笑一下再回来）")
            _face("happy")
            time.sleep(0.6)
            _face(auto_face(feel))
        else:
            print("表情窗口：没开起来（不影响说话；双击「启动表情.command」可以单独开）")

    if args.once:
        turn(agent, cfg, feel, speak_on, args.once)
        feel.save()
        save_summary(agent)
        face_down()
        return 0
    if args.talk:
        try:
            return run_talk(agent, cfg, feel, pr, al)
        finally:
            face_down()
    try:
        return run_text(agent, cfg, feel, speak_on, al)
    finally:
        save_summary(agent)
        face_down()


if __name__ == "__main__":
    sys.exit(main())
