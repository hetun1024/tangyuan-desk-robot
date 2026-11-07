"""声纹：判断这句话是不是"他"说的。

跟语音识别是两件事：
    whisper     声音 → 文字（说了什么）
    声纹        声音 → 是谁（谁说的）

系统是三层判定，不是二选一：

    score >= 高阈值     主人，正常对话
    中间地带            不确定，问一句"是你在说话吗"
    score <= 低阈值     别人，进"客人模式"：能应声，但不碰私事

实现上先用**MFCC 统计量**（零依赖、当天就能跑）：
    每一帧取 13 个倒谱系数 → 整段取均值/标准差 → 再拼上差分 → 归一化 → 余弦相似度
这个办法在安静环境、2—3 个人之间够用，但比不了深度模型（CAM++ 那类）。

换成深度模型时只要替换 `embed()`，别的都不用动。
"""
from __future__ import annotations

import json
import os
from typing import List, Optional

SR = 16000
N_MELS = 26
N_MFCC = 13
FRAME = 400  # 25ms
HOP = 160  # 10ms


def _mel_filterbank(n_mels: int = N_MELS, nfft: int = 512, sr: int = SR):
    import numpy as np

    def hz2mel(f):
        return 2595.0 * np.log10(1.0 + f / 700.0)

    def mel2hz(m):
        return 700.0 * (10.0 ** (m / 2595.0) - 1.0)

    lo, hi = hz2mel(60.0), hz2mel(sr / 2.0)
    mels = np.linspace(lo, hi, n_mels + 2)
    hz = mel2hz(mels)
    bins = np.floor((nfft + 1) * hz / sr).astype(int)
    fb = np.zeros((n_mels, nfft // 2 + 1), np.float32)
    for i in range(n_mels):
        l, c, r = bins[i], bins[i + 1], bins[i + 2]
        for k in range(l, c):
            if c > l:
                fb[i, k] = (k - l) / (c - l)
        for k in range(c, r):
            if r > c:
                fb[i, k] = (r - k) / (r - c)
    return fb


_FB = None


def _dct_matrix(n_out: int, n_in: int):
    import numpy as np

    m = np.zeros((n_out, n_in), np.float32)
    for i in range(n_out):
        for j in range(n_in):
            m[i, j] = np.cos(np.pi * i * (j + 0.5) / n_in)
    m[0] *= 1.0 / np.sqrt(2.0)
    return m * np.sqrt(2.0 / n_in)


def mfcc(pcm: bytes):
    """一段 16k/16bit 单声道 → (T, 13) 的倒谱系数。"""
    import numpy as np

    global _FB, _DCT
    if _FB is None:
        _FB = _mel_filterbank()
        _DCT = _dct_matrix(N_MFCC, N_MELS)

    x = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768.0
    if x.size < FRAME * 3:
        return None
    x = np.append(x[0], x[1:] - 0.97 * x[:-1])  # 预加重

    n = 1 + (len(x) - FRAME) // HOP
    idx = np.arange(FRAME)[None, :] + HOP * np.arange(n)[:, None]
    frames = x[idx] * np.hamming(FRAME)

    spec = np.abs(np.fft.rfft(frames, 512)) ** 2
    mel = spec @ _FB.T
    logmel = np.log(mel + 1e-8)
    return logmel @ _DCT.T


def embed(pcm: bytes) -> Optional[List[float]]:
    """一段语音 → 一个定长向量（52 维）。"""
    import numpy as np

    c = mfcc(pcm)
    if c is None:
        return None
    d = np.diff(c, axis=0) if c.shape[0] > 1 else np.zeros_like(c)
    v = np.concatenate([c.mean(0), c.std(0), d.mean(0), d.std(0)])
    norm = float(np.linalg.norm(v))
    if norm < 1e-6:
        return None
    return (v / norm).astype(float).tolist()


def cosine(a: List[float], b: List[float]) -> float:
    import numpy as np

    va, vb = np.array(a, np.float32), np.array(b, np.float32)
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    if na < 1e-6 or nb < 1e-6:
        return 0.0
    return float(va @ vb / (na * nb))


class Voiceprint:
    """他一个人的声纹。存 data/voiceprint.json。"""

    def __init__(self, path: str):
        self.path = path
        self.pack: Optional[List[List[float]]] = None
        self.lo = 0.55  # 低于这个 = 别人
        self.hi = 0.75  # 高于这个 = 他
        self.load()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                d = json.load(fh)
            self.pack = d.get("pack") or None
            self.lo = float(d.get("lo", self.lo))
            self.hi = float(d.get("hi", self.hi))
        except Exception:  # noqa: BLE001
            self.pack = None

    @property
    def enrolled(self) -> bool:
        return bool(self.pack)

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"pack": self.pack, "lo": self.lo, "hi": self.hi}, fh)

    def enroll(self, samples: List[bytes]) -> str:
        vecs = [v for v in (embed(p) for p in samples) if v]
        if len(vecs) < 2:
            return "录音太短或太安静，至少要成功采到两段。"
        self.pack = vecs
        # 阈值用他自己的几段录音互相比出来，而不是写死一个数
        intra = [cosine(vecs[i], vecs[j]) for i in range(len(vecs)) for j in range(i + 1, len(vecs))]
        base = sum(intra) / len(intra)
        self.hi = max(0.62, base - 0.12)
        self.lo = max(0.45, self.hi - 0.14)
        self.save()
        return "学好了。你自己的声音相似度 %.2f，我按 %.2f / %.2f 分主人和客人。" % (base, self.hi, self.lo)

    def judge(self, pcm: bytes) -> dict:
        """返回 {who, score}。who: owner / unsure / guest。"""
        if not self.pack:
            return {"who": "unknown", "score": 0.0}
        v = embed(pcm)
        if not v:
            return {"who": "unknown", "score": 0.0}
        score = max(cosine(v, p) for p in self.pack)
        who = "owner" if score >= self.hi else ("guest" if score <= self.lo else "unsure")
        return {"who": who, "score": round(score, 3)}
