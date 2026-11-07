"""心情：从**声音本身**听情绪，不靠文字猜。

文字会骗人 —— 你打字说"我没事"，和你说"我没事"时候的语气，是两件事。
所以这里看的是话说完之后留下的那串波形：

  * 音量（RMS → dBFS）：声音大还是小
  * 音高（基频 f0）：说话高还是低

但绝对数值因人而异（有人天生嗓门大），所以**不看绝对值，只看和这个人自己
的平时比**。前几句建立基准，后面比较倍数。样本不够的时候宁可说"听不出"，
也不要瞎猜 —— 一个总在乱猜心情的机器人比不猜的更烦人。
"""
from __future__ import annotations

import statistics
from typing import Dict, List, Optional

SR = 16000
FRAME = 640  # 40ms
F0_MIN, F0_MAX = 70.0, 400.0


def _db(chunk) -> float:
    import numpy as np

    rms = float(np.sqrt(np.mean(chunk * chunk))) if chunk.size else 0.0
    return 20.0 * (np.log10(rms / 32768.0) if rms > 1 else -6.0)


def _f0(chunk, sr: int = SR) -> Optional[float]:
    """自相关估基频。只在有声帧上算，静音帧返回 None。"""
    import numpy as np

    if np.max(np.abs(chunk)) < 200:
        return None
    x = chunk - np.mean(chunk)
    ac = np.correlate(x, x, mode="full")[len(x) - 1 :]
    if ac[0] <= 0:
        return None
    lo, hi = int(sr / F0_MAX), int(sr / F0_MIN)
    if hi >= len(ac):
        return None
    seg = ac[lo:hi]
    if seg.size == 0:
        return None
    lag = int(np.argmax(seg)) + lo
    if lag <= 0:
        return None
    peak = ac[lag] / ac[0]
    if peak < 0.3:  # 不够周期，当成噪声
        return None
    return sr / lag


def analyze(pcm: bytes) -> Dict[str, float]:
    """一段 16k/16bit 单声道录音 → 音量、音高、有声比例。"""
    import numpy as np

    data = np.frombuffer(pcm, np.int16).astype(np.float32)
    if data.size < FRAME * 3:
        return {"db": -60.0, "pitch": 0.0, "voiced": 0.0}

    frames = [data[i : i + FRAME] for i in range(0, len(data) - FRAME, FRAME)]
    dbs = [_db(f) for f in frames]
    loud = [f for f, d in zip(frames, dbs) if d > -45]
    if not loud:
        return {"db": max(dbs) if dbs else -60.0, "pitch": 0.0, "voiced": 0.0}

    pitches = [p for p in (_f0(f) for f in loud) if p]
    return {
        "db": statistics.median([d for d in dbs if d > -45]) if any(d > -45 for d in dbs) else -60.0,
        "pitch": statistics.median(pitches) if pitches else 0.0,
        "voiced": len(loud) / max(len(frames), 1),
    }


class Mood:
    """记住"这个人平时什么样"，然后才知道这一句是不是不一样。"""

    def __init__(self, window: int = 12):
        self.window = window
        self.history: List[Dict[str, float]] = []

    def read(self, pcm: bytes) -> Dict[str, object]:
        feat = analyze(pcm)
        self.history.append(feat)
        self.history = self.history[-self.window :]
        return self._judge(feat)

    def _judge(self, feat: Dict[str, float]) -> Dict[str, object]:
        base = self.history[:-1]
        out = {"mood": "平稳", "hint": "", "rate": 175, "db": round(feat["db"], 1),
               "pitch": round(feat["pitch"], 1)}

        if len(base) < 3 or feat["pitch"] <= 0:
            out["hint"] = "（还听不出情绪，样本太少）"
            return out

        db0 = statistics.median([b["db"] for b in base])
        p0 = statistics.median([b["pitch"] for b in base if b["pitch"] > 0] or [feat["pitch"]])

        louder = feat["db"] - db0
        higher = feat["pitch"] - p0

        if louder > 3.0 and higher > 8:
            out.update(mood="有精神", rate=195,
                       hint="这句比平时声音大、调门高，像是精神不错或者有点着急。")
        elif louder > 3.0:
            out.update(mood="有精神", rate=190,
                       hint="这句比平时声音大，听着挺有劲。")
        elif louder < -3.0 and higher < -15:
            out.update(mood="低落", rate=150,
                       hint="这句比平时声音小、调门低，可能有点累或者心情一般。")
        elif louder < -4.0:
            out.update(mood="疲惫", rate=158,
                       hint="这句比平时轻很多，可能累了。")
        else:
            out["hint"] = "语气和平时差不多。"
        return out
