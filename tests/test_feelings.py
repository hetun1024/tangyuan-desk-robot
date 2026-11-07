#!/usr/bin/env python3
"""情绪系统的测试：会变、会退、会记住、能说清为什么。"""
from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.feelings import Feelings  # noqa: E402


def fresh() -> Feelings:
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    return Feelings(path=path)


def test_一开始是中性的():
    f = fresh()
    assert -0.1 < f.valence < 0.2
    assert 0.4 < f.energy < 0.7
    assert f.intimacy == 0.0


def test_被夸会好一点一点点():
    f = fresh()
    v0 = f.valence
    f.event("praise")
    assert f.valence > v0
    assert f.valence - v0 < 0.2, "一次夸奖不该有巨大变化"


def test_被冷落会低一点():
    f = fresh()
    v0 = f.valence
    f.event("ignored")
    assert f.valence < v0


def test_不做任何事会漂回基线():
    f = fresh()
    f.valence = -0.9
    f.energy = 1.0
    f.tick()
    assert f.valence > -0.9, "应该往回走，而不是越陷越深"
    assert f.energy < 1.0


def test_太久没见关系会淡():
    f = fresh()
    f.intimacy = 0.5
    f.last_seen = (dt.datetime.now() - dt.timedelta(hours=100)).isoformat(timespec="seconds")
    f.tick()
    assert f.intimacy < 0.5


def test_存盘能读回来():
    f = fresh()
    f.event("praise")
    f.intimacy = 0.42
    f.save()
    again = Feelings.load(f.path)
    assert abs(again.intimacy - 0.42) < 1e-6
    assert again.valence > 0


def test_能说清为什么():
    f = fresh()
    f.event("ignored", "十分钟没理")
    p = f.prompt()
    assert "被冷落" in p
    assert "心情" in p


def test_心情影响语速():
    f = fresh()
    f.energy = 0.05
    slow = f.voice_rate()
    f.energy = 0.95
    fast = f.voice_rate()
    assert fast > slow, (slow, fast)
    assert 140 <= slow <= 210 and 140 <= fast <= 210


def test_连续天数会记():
    f = fresh()
    f.mark_spoke()
    f.mark_spoke()
    assert f.streak_days == 1


def test_夜里精力低白天高():
    from agent.feelings import _circadian_energy

    assert _circadian_energy(3) < _circadian_energy(12)
    assert _circadian_energy(23) < _circadian_energy(20)


def test_认识天数从第一面算():
    f = fresh()
    f.first_met = (dt.datetime.now() - dt.timedelta(days=6)).isoformat(timespec="seconds")
    assert f.days_known == 7


def test_隔很久回来会闹别扭():
    f = fresh()
    f.valence = -0.2
    f.session_gap = 30.0
    assert f.sulk


def test_刚聊过就不闹别扭():
    f = fresh()
    f.valence = 0.0
    f.session_gap = 0.1
    assert not f.sulk


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
