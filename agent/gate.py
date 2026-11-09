"""谁能指挥她。

声纹（判断"是不是你"）实测还不可靠 —— 跨说话人相似度 0.83—0.88，
主人自比 0.95，差距太小。所以这一层先用一个更笨但可靠的办法：

    叫她的名字，才算在跟她说话

规则：
  * 听到唤醒词（默认「汤圆」）→ 开启一个 20 秒的授权窗口，这期间她肯动手
  * 只有再叫一次名字才续期（别人在旁边说话不该续）
  * 没叫过名字就让她开应用、锁屏、写备忘录 → 拒绝，并说一句"你叫我一声"

为什么不直接禁掉：陌生人问"现在几点"是没关系的，
真正需要拦的是**能改你电脑**的那些动作。

声纹以后调好了，把 judge() 接进这里就行，上面那套授权逻辑不用动。
"""
from __future__ import annotations

import time

WINDOW = 20.0  # 授权窗口（秒）

OPEN_TOOLS = {
    "open_app", "screenshot", "write_note", "set_volume", "notify", "open_url",
    "list_files", "control_music", "lock_screen", "run_shell", "look_at_screen",
    "make_appointment", "complete_appointment", "cancel_alarm", "forget_fact",
    "remember_sensitive", "remember_fact", "remember",
}


class Gate:
    def __init__(self, wake_word: str = "汤圆", window: float = WINDOW, enabled: bool = True):
        self.wake = (wake_word or "").strip()
        self.window = window
        self.enabled = enabled and bool(self.wake)
        self.until = 0.0
        self.owner = False

    def hear(self, text: str, now: float | None = None) -> bool:
        """他说的这句话里有没有叫她的名字。有就续期。"""
        now = time.monotonic() if now is None else now
        if not self.enabled:
            return True
        if self.wake and self.wake in (text or ""):
            self.until = now + self.window
            return True
        return now < self.until

    def open(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        if not self.enabled:
            return True
        return now < self.until

    def allow(self, tool_name: str, now: float | None = None) -> bool:
        if tool_name not in OPEN_TOOLS:
            return True  # 只读、无害的工具不拦
        return self.open(now)

    def remain(self, now: float | None = None) -> float:
        now = time.monotonic() if now is None else now
        return max(0.0, self.until - now)
