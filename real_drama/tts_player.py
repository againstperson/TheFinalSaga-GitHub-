# name=real_drama/tts_player.py
import pyttsx3
import threading
import time

class TTSPlayer:
    def __init__(self, rate_multiplier=1.25, voice_name=""):
        self.engine = pyttsx3.init()
        # store default rate
        self.base_rate = self.engine.getProperty("rate")
        self.set_rate_multiplier(rate_multiplier)
        if voice_name:
            voices = self.engine.getProperty("voices")
            for v in voices:
                if voice_name.lower() in v.name.lower():
                    self.engine.setProperty("voice", v.id)
                    break

        # run in background thread so caller isn't blocked when desired
        self._lock = threading.Lock()

    def set_rate_multiplier(self, m):
        try:
            new_rate = int(self.base_rate * float(m))
        except Exception:
            new_rate = int(self.base_rate * 1.25)
        self.engine.setProperty("rate", new_rate)

    def speak(self, text, block=True):
        def _speak():
            with self._lock:
                self.engine.say(text)
                self.engine.runAndWait()
        t = threading.Thread(target=_speak, daemon=True)
        t.start()
        if block:
            t.join()
