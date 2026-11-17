"""ارسال به تلگرام (پیام متنی، عکس+کپشن، ریپلای، بی‌صدا). حالت dry: فقط چاپ و ذخیره‌ی چارت."""
import json
import os
import re
import time

import requests


class TelegramError(Exception):
    pass


class Telegram:
    def __init__(self, token, chat_id, dry=False, out_dir="out"):
        self.token, self.chat_id = token, chat_id
        self.dry = dry or not (token and chat_id)
        self.out_dir = out_dir
        self.fake_id = 1000
        self.s = requests.Session()

    def _post(self, method, data, files=None, tries=4):
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        err = "?"
        for k in range(tries):
            try:
                r = self.s.post(url, data=data, files=files, timeout=(5, 25))
                j = r.json()
            except Exception as e:                      # خطای شبکه → دوباره
                err = f"{type(e).__name__}"
                time.sleep(1.0 * (k + 1))
                continue
            if j.get("ok"):
                return j["result"]
            err = str(j.get("description"))
            if r.status_code == 429:
                time.sleep(min(30, j.get("parameters", {}).get("retry_after", 3)) + 0.5)
                continue
            if r.status_code >= 500:
                time.sleep(1.0 * (k + 1))
                continue
            break
        raise TelegramError(err)

    def _base(self, silent, reply_to):
        d = {"chat_id": self.chat_id, "parse_mode": "HTML", "disable_notification": "true" if silent else "false"}
        if reply_to:
            d["reply_parameters"] = json.dumps({"message_id": reply_to, "allow_sending_without_reply": True})
        return d

    def send_text(self, text, reply_to=None, silent=False):
        if self.dry:
            self.fake_id += 1
            print(f"\n--- [dry] پیام #{self.fake_id} (reply={reply_to}, silent={silent}) ---\n{text}\n")
            return self.fake_id
        d = self._base(silent, reply_to)
        d["text"] = text
        d["disable_web_page_preview"] = "true"
        try:
            return self._post("sendMessage", d)["message_id"]
        except TelegramError as e:
            if "parse" in str(e).lower():
                d.pop("parse_mode")
                d["text"] = re.sub(r"</?[a-z]+>", "", text)
                return self._post("sendMessage", d)["message_id"]
            raise

    def send_photo(self, png: bytes, caption: str, silent=False):
        if self.dry:
            self.fake_id += 1
            os.makedirs(self.out_dir, exist_ok=True)
            p = os.path.join(self.out_dir, f"chart_{self.fake_id}.png")
            open(p, "wb").write(png)
            print(f"\n--- [dry] عکس #{self.fake_id} → {p} (silent={silent}) ---\n{caption}\n")
            return self.fake_id
        d = self._base(silent, None)
        d["caption"] = caption
        try:
            return self._post("sendPhoto", d, files={"photo": ("chart.png", png, "image/png")})["message_id"]
        except TelegramError as e:
            if "parse" in str(e).lower():
                d.pop("parse_mode")
                d["caption"] = re.sub(r"</?[a-z]+>", "", caption)
                return self._post("sendPhoto", d, files={"photo": ("chart.png", png, "image/png")})["message_id"]
            raise
