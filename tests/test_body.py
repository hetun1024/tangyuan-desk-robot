#!/usr/bin/env python3
"""身体接口的测试：工厂选对实现、NetBody 会把请求发出去。"""
from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.body import BodyError, MacBody, NetBody, make_body  # noqa: E402
from agent.config import Config  # noqa: E402


def test_默认用本机():
    assert isinstance(make_body(Config()), MacBody)


def test_配了地址就用网络():
    assert isinstance(make_body(Config(body="net", body_url="http://127.0.0.1:1")), NetBody)


def test_没有地址会报错():
    try:
        NetBody(Config(body="net", body_url=""))
        raise AssertionError("应该报错")
    except BodyError as e:
        assert "body_url" in str(e)


def test_网络身体会真的发请求():
    seen = {}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("content-length", 0))
            seen[self.path] = json.loads(self.rfile.read(n) or b"{}")
            data = b'{"ok": true, "text": "\xe4\xbd\xa0\xe5\xa5\xbd"}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    body = NetBody(Config(body="net", body_url="http://127.0.0.1:%d" % srv.server_address[1]))

    body.speak("测试", rate=180)
    assert seen["/speak"]["text"] == "测试"
    assert seen["/speak"]["rate"] == 180

    body.face("happy")
    assert seen["/face"]["emotion"] == "happy"

    assert body.listen() == "你好"
    srv.shutdown()


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
