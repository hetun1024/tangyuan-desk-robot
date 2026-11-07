"""耳朵：麦克风 → 文字。

两个识别后端，同一个接口：

  * whisper（默认）—— faster-whisper，中文准得多，模型 75—500MB，离线
  * vosk          —— 44MB 的老模型，快但容易错字，做后备

采集那一层是共用的，也是这一版重写过的重点：

1. 音频流只开一次，全程开着。以前每听一句都要重新打开麦克风，
   设备初始化 200—300ms，这半秒里说的话直接没了。
2. 预录缓冲。检测到"有人开口"之后，把之前约 1 秒的音频一起吐给识别器。
   实测：剪掉 150ms 开头就丢第一个字，剪 500ms 丢前三个字。
3. 静音判定 1.2 秒。人说话中间本来就有停顿，0.7 秒会把一句话切成两半。
"""
from __future__ import annotations

import collections
import os
import glob
import queue
import sys
import time
import wave

# 下模型这一步在国内很容易卡住：默认源慢，xet 加速还会因为写缓存失败。
# 只在用户没自己设过的时候兜底，别覆盖他的选择。
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

# whisper 的 FFT 在某些音频上会刷一堆 RuntimeWarning，不影响结果，别吓人
import warnings  # noqa: E402

warnings.filterwarnings("ignore", message=".*matmul.*", category=RuntimeWarning)

SAMPLE_RATE = 16000
BLOCK = 800  # 50ms 一块
PREROLL_BLOCKS = 20  # 预录 1 秒
THRESHOLD = 300.0  # 音量门槛；环境吵就调高

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WHISPER_DIR = os.path.join(HERE, "models", "whisper")


def available(backend: str = "whisper") -> tuple:
    try:
        import sounddevice  # noqa: F401
    except Exception:  # noqa: BLE001
        return False, "缺少 sounddevice：python3 -m pip install --user sounddevice"
    if backend == "whisper":
        try:
            import faster_whisper  # noqa: F401
        except Exception:  # noqa: BLE001
            return False, "缺少 faster-whisper：python3 -m pip install --user faster-whisper"
    else:
        try:
            import vosk  # noqa: F401
        except Exception:  # noqa: BLE001
            return False, "缺少 vosk：python3 -m pip install --user vosk"
    return True, ""


def _rms(chunk: bytes) -> float:
    import numpy as np

    data = np.frombuffer(chunk, np.int16).astype(np.float32)
    return float(np.sqrt(np.mean(data * data))) if data.size else 0.0


class Ears:
    def __init__(
        self,
        model_dir: str = "",
        device=None,
        backend: str = "whisper",
        whisper_size: str = "base",
    ):
        self.backend = backend
        self.model_dir = model_dir or default_model_dir()
        self.whisper_size = whisper_size
        self.device = device
        self.last_audio = b""
        self._q = queue.Queue()
        self._stream = None
        self._vosk = None
        self._whisper = None

    # ---------------------------------------------------------------- 模型
    def _local_model_dir(self):
        """模型已经在本地就直接用路径加载。

        传 "small" 这种名字给 faster-whisper，它会先去 HuggingFace 检查有没有更新
        —— 国内这一步会卡 70 多秒（我实测 76.8s），而本地加载只要 0.6 秒。
        """
        pat = os.path.join(
            WHISPER_DIR, "models--Systran--faster-whisper-%s" % self.whisper_size,
            "snapshots", "*",
        )
        for d in glob.glob(pat):
            if os.path.exists(os.path.join(d, "model.bin")):
                return d
        return None

    def _load(self):
        if self.backend == "whisper":
            from faster_whisper import WhisperModel

            os.makedirs(WHISPER_DIR, exist_ok=True)
            local = self._local_model_dir()
            if local:
                self._whisper = WhisperModel(
                    local, device="cpu", compute_type="int8", local_files_only=True
                )
            else:
                print("  第一次用 whisper，正在下模型（约 %s）…" % (
                    "460MB" if self.whisper_size == "small" else "150MB"))
                self._whisper = WhisperModel(
                    self.whisper_size,
                    device="cpu",
                    compute_type="int8",
                    download_root=WHISPER_DIR,
                )
        else:
            from vosk import Model, SetLogLevel

            SetLogLevel(-1)
            if not os.path.isdir(self.model_dir):
                raise FileNotFoundError(
                    "找不到语音模型目录：%s\n"
                    "把 vosk-model-small-cn-0.22.zip 解压到 models/ 下面就行。" % self.model_dir
                )
            self._vosk = Model(self.model_dir)

    @property
    def name(self) -> str:
        return "whisper-%s" % self.whisper_size if self.backend == "whisper" else "vosk"

    # ------------------------------------------------------------------ 开关
    def start(self):
        import sounddevice as sd

        def cb(indata, frames, time_info, status):  # noqa: ANN001
            try:
                self._q.put_nowait(bytes(indata))
            except queue.Full:
                pass

        try:
            self._stream = sd.RawInputStream(
                samplerate=SAMPLE_RATE,
                blocksize=BLOCK,
                device=self.device,
                dtype="int16",
                channels=1,
                callback=cb,
            )
            self._stream.start()
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                "打不开麦克风（%s）。\n"
                "去「系统设置 → 隐私与安全性 → 麦克风」，把终端打开，再重跑一次。" % e
            ) from e

    def stop(self):
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:  # noqa: BLE001
                pass
            self._stream = None

    def _drain(self, seconds: float = 0.35):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                self._q.get(timeout=0.05)
            except queue.Empty:
                pass

    # -------------------------------------------------------------- 听一句
    def listen(
        self,
        start_timeout: float = 10.0,
        max_seconds: float = 25.0,
        silence: float = 1.2,
        on_status=None,
    ) -> str:
        if self._stream is None:
            self.start()
        self._drain(0.35)
        self.last_audio = b""

        step = BLOCK / SAMPLE_RATE
        silence_need = max(1, int(silence / step))

        pre = collections.deque(maxlen=PREROLL_BLOCKS)
        speech = False
        quiet = loud = 0
        waited = recorded = 0.0
        kept = []

        while True:
            try:
                chunk = self._q.get(timeout=0.5)
            except queue.Empty:
                if not speech:
                    waited += 0.5
                    if waited > start_timeout:
                        return ""
                continue

            level = _rms(chunk)

            if not speech:
                pre.append(chunk)
                waited += step
                loud = loud + 1 if level > THRESHOLD else 0
                if loud >= 3:
                    speech = True
                    kept.extend(pre)  # 把预录的一起留着 —— 开头在这里补回来
                    pre.clear()
                    if on_status:
                        on_status("listening")
                elif waited > start_timeout:
                    return ""
                continue

            kept.append(chunk)
            recorded += step
            quiet = quiet + 1 if level < THRESHOLD else 0
            if quiet > silence_need or recorded > max_seconds:
                break

        self.last_audio = b"".join(kept)
        if not self.last_audio:
            return ""
        return self._decode(self.last_audio)

    # ------------------------------------------------------------------ 识别
    def _decode(self, pcm: bytes) -> str:
        if self._vosk is None and self._whisper is None:
            self._load()
        if self.backend == "vosk":
            return self._decode_vosk(pcm)
        return self._decode_whisper(pcm)

    def _decode_vosk(self, pcm: bytes) -> str:
        import json

        from vosk import KaldiRecognizer

        rec = KaldiRecognizer(self._vosk, SAMPLE_RATE)
        for i in range(0, len(pcm), BLOCK):
            rec.AcceptWaveform(pcm[i : i + BLOCK])
        return json.loads(rec.FinalResult()).get("text", "").replace(" ", "")

    def _decode_whisper(self, pcm: bytes) -> str:
        import numpy as np

        audio = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768.0
        if audio.size < SAMPLE_RATE * 0.2:  # 太短，不值得跑模型
            return ""
        segments, _info = self._whisper.transcribe(
            audio,
            language="zh",
            beam_size=5,
            vad_filter=False,
            condition_on_previous_text=False,
            initial_prompt="以下是普通话的句子。",
        )
        return "".join(s.text for s in segments).replace(" ", "").strip()

    # ------------------------------------------------------- 从音频文件测
    def transcribe_wav(self, path: str) -> str:
        with wave.open(path, "rb") as wf:
            pcm = wf.readframes(wf.getnframes())
        return self._decode(pcm)


def default_model_dir() -> str:
    return os.path.join(HERE, "models", "vosk-model-small-cn-0.22")


if __name__ == "__main__":
    backend = sys.argv[2] if len(sys.argv) > 2 else "whisper"
    ok, why = available(backend)
    if not ok:
        print(why)
        sys.exit(1)
    ears = Ears(backend=backend)
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        print(ears.transcribe_wav(sys.argv[1]))
    else:
        ears.start()
        print("说完一句就会显示出来。Ctrl-C 退出。")
        try:
            while True:
                print("你说：", ears.listen())
        finally:
            ears.stop()
