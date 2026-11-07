"""眼睛的第二层：把屏幕截图交给一个"看得见"的模型。

为什么要单独一个接口：对话用的 DeepSeek 是纯文本模型，看不见图。所以视觉
要另配一个端点（智谱 GLM-4V、通义 qwen-vl 之类），它们的接口都是同一套
OpenAI 兼容格式 —— 和 brain.py 一样，换供应商只改三个字符串。

没配也不会坏：工具会老实说"还没接上视觉模型"，其余功能照常。
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from typing import Optional

MAX_SIDE = 1600  # 截图先缩到这个尺寸，省 token 也省时间


class VisionError(RuntimeError):
    pass


def available(cfg) -> tuple:
    if not getattr(cfg, "vision_api_key", ""):
        return False, (
            "还没配视觉模型。\n"
            "去 config.json 填 vision_api_key / vision_model / vision_base_url ——\n"
            "智谱 GLM-4V-Flash 有免费额度，最划算。"
        )
    try:
        import cv2  # noqa: F401
    except Exception:  # noqa: BLE001
        return False, "缺少 opencv，缩图用不了。"
    return True, ""


def _to_data_url(path: str) -> str:
    """把图片读进来、缩一下、转成 base64 的 data URL。"""
    import cv2
    import numpy as np

    data = np.fromfile(path, dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise VisionError("读不到这张图：%s" % path)

    h, w = img.shape[:2]
    if max(h, w) > MAX_SIDE:
        k = MAX_SIDE / float(max(h, w))
        img = cv2.resize(img, (int(w * k), int(h * k)), interpolation=cv2.INTER_AREA)

    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
    if not ok:
        raise VisionError("图片压缩失败。")
    b64 = base64.b64encode(buf.tobytes()).decode("ascii")
    return "data:image/jpeg;base64," + b64


def ask_about(cfg, image_path: str, question: str) -> str:
    """看着一张图回答问题。"""
    ok, why = available(cfg)
    if not ok:
        return why

    url = cfg.vision_base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": cfg.vision_model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": question or "这张图上有什么？用一两句话说说。"},
                    {"type": "image_url", "image_url": {"url": _to_data_url(image_path)}},
                ],
            }
        ],
        "max_tokens": 600,
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + cfg.vision_api_key,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout_s) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8")[:300]
        except Exception:  # noqa: BLE001
            pass
        if e.code == 401:
            raise VisionError("视觉模型的 key 不对（401）。") from e
        if e.code == 402:
            raise VisionError("视觉模型账户没钱了（402）。") from e
        raise VisionError("视觉模型返回 %d：%s" % (e.code, detail)) from e
    except urllib.error.URLError as e:
        raise VisionError("连不上视觉模型（%s）。检查 vision_base_url。" % e.reason) from e
    except TimeoutError as e:
        raise VisionError("视觉模型超时了。") from e

    try:
        return (body["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError) as e:
        raise VisionError("视觉模型返回看不懂：%s" % str(body)[:200]) from e
