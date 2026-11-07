#!/usr/bin/env python3
"""约定系统的测试：记下、到期、过期、问过。"""
from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.promises import Promises  # noqa: E402


def fresh() -> Promises:
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    return Promises(path)


def day(offset: int) -> str:
    return (dt.date.today() + dt.timedelta(days=offset)).isoformat()


def test_记一条再查():
    p = fresh()
    assert "记下了" in p.add("面试", day(1))
    assert len(p.pending()) == 1


def test_今天到期能查出来():
    p = fresh()
    p.add("面试", day(0))
    assert len(p.due_today()) == 1


def test_过期的能查出来():
    p = fresh()
    p.add("体检", day(2))
    # 过去的日子不让新建，所以先建一条再改日期
    p.items[0]["due"] = day(-2)
    assert len(p.overdue()) == 1


def test_过去的日子不让记():
    p = fresh()
    assert "已经过去" in p.add("补牙", day(-3))


def test_日期格式不对会拒绝():
    p = fresh()
    assert "YYYY-MM-DD" in p.add("面试", "明天")


def test_标完成之后不再提醒():
    p = fresh()
    p.add("面试", day(0))
    p.done(0)
    assert p.pending() == []
    assert p.due_today() == []


def test_存盘能读回来():
    p = fresh()
    p.add("面试", day(1))
    again = Promises(p.path)
    assert len(again.pending()) == 1


def test_提示词里会提到到期的事():
    p = fresh()
    p.add("面试", day(0))
    assert "面试" in p.prompt()


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
