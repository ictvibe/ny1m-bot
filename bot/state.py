"""ذخیره‌ی وضعیت (برای جلوگیری از ارسال تکراری وقتی ربات وسط بازه دوباره اجرا شود).
فایل state/state.json در شاخه‌ی جدای bot-state مخزن ذخیره می‌شود (در پس‌زمینه commit و push)."""
import json
import os
import subprocess
import threading


class State:
    def __init__(self, dirpath="state"):
        self.dir = dirpath
        self.path = os.path.join(dirpath, "state.json")
        self.git = os.path.exists(os.path.join(dirpath, ".git"))
        self.data = {}
        self._lock = threading.Lock()
        self._dirty = False
        self._thread = None

    def load(self, day: str):
        os.makedirs(self.dir, exist_ok=True)
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            d = {}
        if d.get("day") != day:                       # روز جدید: ناحیه‌ها به روز بعد نمی‌روند
            d = {"day": day, "start_sent": False, "end_sent": False, "zones": {}, "stale": {},
                 "lag_data": [], "lag_send": []}
        self.data = d

    @property
    def zones(self):
        return self.data["zones"]

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)
        if self.git:
            with self._lock:
                self._dirty = True
                if not self._thread or not self._thread.is_alive():
                    self._thread = threading.Thread(target=self._push_loop, daemon=True)
                    self._thread.start()

    def _run(self, *args):
        return subprocess.run(["git", "-C", self.dir, *args], capture_output=True, text=True, timeout=90)

    def _push_loop(self):
        while True:
            with self._lock:
                if not self._dirty:
                    return
                self._dirty = False
            try:
                self._run("add", "-A")
                self._run("commit", "-m", f"state {self.data.get('day')}", "--allow-empty-message", "-q")
                if self._run("push", "origin", "bot-state").returncode != 0:
                    self._run("pull", "--rebase", "origin", "bot-state")
                    self._run("push", "origin", "bot-state")
            except Exception as e:                    # ذخیره‌ی ناموفق نباید ربات را متوقف کند
                print("state push failed:", e, flush=True)

    def flush(self):
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=120)
