#!/usr/bin/env python3
"""门禁的测试：没叫名字不许动电脑。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.gate import Gate  # noqa: E402


def test_没叫名字不许开应用():
    g = Gate("汤圆", window=20)
    assert not g.allow("open_app", now=0)


def test_叫了名字就允许():
    g = Gate("汤圆", window=20)
    g.hear("汤圆，帮我打开计算器", now=0)
    assert g.allow("open_app", now=0)


def test_授权会过期():
    g = Gate("汤圆", window=20)
    g.hear("汤圆", now=0)
    assert g.allow("open_app", now=19)
    assert not g.allow("open_app", now=21)


def test_只有叫名字才续期():
    """别人在你旁边说话，不该把授权继续拖下去。"""
    g = Gate("汤圆", window=20)
    g.hear("汤圆", now=0)
    g.hear("在吗", now=15)          # 没带名字 → 不续期
    assert not g.allow("open_app", now=30)
    g.hear("汤圆", now=30)          # 再叫一次 → 续到 50
    assert g.allow("open_app", now=45)


def test_无害的工具不拦():
    g = Gate("汤圆", window=20)
    assert g.allow("get_time", now=0)
    assert g.allow("look_around", now=0)


def test_关掉门禁就都放行():
    g = Gate("汤圆", enabled=False)
    assert g.allow("open_app", now=0)


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
