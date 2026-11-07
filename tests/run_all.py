#!/usr/bin/env python3
"""跑 tests/ 下所有 test_*.py。"""
from __future__ import annotations

import importlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)


def main() -> int:
    tests = []
    for name in sorted(os.listdir(HERE)):
        if name.startswith("test_") and name.endswith(".py"):
            mod = importlib.import_module(name[:-3])
            for attr in sorted(dir(mod)):
                if attr.startswith("test_"):
                    tests.append(("%s.%s" % (name[:-3], attr), getattr(mod, attr)))
    failed = 0
    for label, fn in tests:
        try:
            fn()
            print("ok    %s" % label)
        except AssertionError as e:
            failed += 1
            print("FAIL  %s: %s" % (label, e))
        except Exception as e:  # noqa: BLE001
            failed += 1
            print("ERROR %s: %s: %s" % (label, type(e).__name__, e))
    print("\n%d/%d passed" % (len(tests) - failed, len(tests)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
