"""眼睛：看一眼，然后告诉大脑"现在是什么情况"。

和人一样，看一眼只需要一小会儿 —— 这里抓 8 帧（约半秒），取人脸最多的
那一帧的判断，而不是只信一帧的偶然结果。

输出两种东西：
  * data —— 给程序用的数字
  * text —— 给大模型看的一句话（模型不擅长读数字，擅长读句子）

摄像头的权限是这一层最容易卡住的地方，所以错误提示写得啰嗦一点。
"""
from __future__ import annotations

import math
import os

MODEL = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "models",
    "face_detection_yunet_2023mar.onnx",
)

# 和盯盯那套用的是同一组参数：抬头低头 ±18°/±15° 算"在看我"
LOOK_YAW = 18.0
LOOK_PITCH = 15.0
NEAR_AREA = 0.06  # 脸占画面 6% 以上算"离得近"


def available() -> tuple:
    try:
        import cv2  # noqa: F401
    except Exception:  # noqa: BLE001
        return False, "缺少 opencv：python3 -m pip install --user opencv-python"
    if not os.path.exists(MODEL):
        return False, "缺少人脸模型：models/face_detection_yunet_2023mar.onnx"
    return True, ""


def _pose(pts):
    """5 个关键点 → 头偏了几度。用同帧瞳距归一化，所以远近不影响读数。"""
    import numpy as np

    r_eye, l_eye, nose = pts[0], pts[1], pts[2]
    eye_mid = (r_eye + l_eye) / 2.0
    iod = float(np.linalg.norm(l_eye - r_eye))
    if iod < 1e-3:
        return 0.0, 0.0
    yaw = (float(nose[0]) - float(eye_mid[0])) / iod * 100.0
    pitch = ((float(nose[1]) - float(eye_mid[1])) / iod - 0.55) * 90.0
    return yaw, pitch


class Eye:
    def __init__(self, model_path: str = MODEL):
        import cv2

        self.cv2 = cv2
        self.det = cv2.FaceDetectorYN.create(model_path, "", (640, 480), 0.6, 0.3, 50)
        self._size = (0, 0)

    def _detect(self, frame):
        cv2 = self.cv2
        h, w = frame.shape[:2]
        if self._size != (w, h):
            self.det.setInputSize((w, h))
            self._size = (w, h)
        _, raw = self.det.detect(frame)
        out = []
        if raw is None:
            return out
        for row in raw:
            x, y, fw, fh = (float(v) for v in row[:4])
            if fw < 2 or fh < 2:
                continue
            import numpy as np

            pts = np.asarray(row[4:14], dtype=np.float32).reshape(5, 2)
            yaw, pitch = _pose(pts)
            out.append(
                {
                    "yaw": yaw,
                    "pitch": pitch,
                    "area": (fw * fh) / float(w * h),
                    "score": float(row[14]),
                }
            )
        return out

    @staticmethod
    def _err(msg: str) -> dict:
        return {"error": msg, "text": msg, "n_faces": 0, "n_looking": 0,
                "nearest_area": 0.0, "situation": "看不到"}

    def look_at_image(self, path: str) -> dict:
        from .imgio import imread

        img = imread(path)
        if img is None:
            return self._err("读不到这张图：%s" % path)
        return self._summarize(self._detect(img))

    def look(self, camera: int = 0, frames: int = 8) -> dict:
        """看一眼摄像头。抓 frames 帧，取人脸最多的那帧。"""
        cv2 = self.cv2
        cap = cv2.VideoCapture(camera)
        if not cap.isOpened():
            return self._err(
                "打不开摄像头。去「系统设置 → 隐私与安全性 → 摄像头」给终端授权；"
                "也可能是摄像头正被别的程序占着（腾讯会议 / Zoom 之类）。"
            )
        best = []
        try:
            for _ in range(frames):
                ok, frame = cap.read()
                if not ok:
                    break
                faces = self._detect(frame)
                if len(faces) > len(best):
                    best = faces
                if len(faces) >= 2:
                    break
        finally:
            cap.release()

        if not best:
            # 再试一帧，区分"真的没人"和"没读到画面"
            return self._summarize([])
        return self._summarize(best)

    # ------------------------------------------------------------ 说人话
    def _summarize(self, faces) -> dict:
        looking = [
            f for f in faces if abs(f["yaw"]) <= LOOK_YAW and abs(f["pitch"]) <= LOOK_PITCH
        ]
        nearest = max((f["area"] for f in faces), default=0.0)

        if not faces:
            mood = "没人在"
            text = "画面里没有人。"
        elif looking:
            distance = "很近" if nearest >= NEAR_AREA else "有点远" if nearest >= 0.02 else "挺远"
            text = "有 %d 个人，其中 %d 个正在看着你，人离得%s。" % (
                len(faces),
                len(looking),
                distance,
            )
            mood = "被注视"
        else:
            text = "画面里有 %d 个人，但没人在看你。" % len(faces)
            mood = "被无视"

        return {
            "n_faces": len(faces),
            "n_looking": len(looking),
            "nearest_area": round(nearest, 4),
            "situation": mood,
            "text": text,
        }


def brightness(camera: int = 0) -> float | None:
    """用摄像头当光传感器：画面平均亮度 0—255。

    没装光敏电阻也能知道"房间暗不暗" —— 摄像头本来就在测光。
    """
    try:
        import cv2

        cap = cv2.VideoCapture(camera)
        if not cap.isOpened():
            return None
        ok, frame = cap.read()
        cap.release()
        if not ok or frame is None:
            return None
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return float(gray.mean())
    except Exception:  # noqa: BLE001
        return None


def look_summary(**kw) -> str:
    ok, why = available()
    if not ok:
        return why
    try:
        return Eye().look(**kw)["text"]
    except Exception as e:  # noqa: BLE001
        return "看不了：%s" % e


if __name__ == "__main__":
    ok, why = available()
    print("眼睛可用" if ok else why)
    if ok:
        print(look_summary(frames=3))
