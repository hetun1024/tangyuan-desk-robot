#!/usr/bin/env python3
"""闹钟的测试：设、到点、取消、过期不叫。"""
from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.alarms import Alarms, in_minutes  # noqa: E402


def fresh() -> Alarms:
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    return Alarms(path)


def test_设一个定时():
    a = fresh()
    assert "叫你" in a.add(in_minutes(10), "喝水")
    assert len(a.pending()) == 1


def test_到点会被叫出来():
    a = fresh()
    a.add(in_minutes(5), "喝水")
    a.items[0]["at"] = in_minutes(-1)  # 改成已经到点
    due = a.due()
    assert len(due) == 1 and due[0]["what"] == "喝水"


def test_叫过就不再叫():
    a = fresh()
    a.add(in_minutes(5), "喝水")
    a.items[0]["at"] = in_minutes(-1)
    a.due()
    assert a.due() == []


def test_取消之后不叫():
    a = fresh()
    a.add(in_minutes(5), "喝水")
    a.cancel(0)
    assert a.due() == []


def test_过去的时间不让设():
    a = fresh()
    assert "已经过去" in a.add("2020-01-01 10:00", "x")


def test_时间看不懂会提示():
    a = fresh()
    assert "看不懂" in a.add("明天", "x")


def test_存盘能读回来():
    a = fresh()
    a.add(in_minutes(30), "开会")
    again = Alarms(a.path)
    assert len(again.pending()) == 1


def test_跨天的小时数会落到明天():
    a = fresh()
    now = dt.datetime.now()
    hour = (now.hour + 2) % 24
    assert "叫你" in a.add("%02d:%02d" % (hour, now.minute), "起床")


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
