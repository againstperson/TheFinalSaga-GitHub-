# name=run_drama.py
import yaml
import os
from real_drama.drama_fetchers import RedditFetcher, YouTubeFetcher, XFetcher, ThreadsFetcher
from real_drama.script_generator import make_debate_script
from real_drama.tts_player import TTSPlayer

def load_config(path="config.yaml"):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Config {path} not found. Copy config.example.yaml to {path} and edit.")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def collect_all(config):
    results = []
    src = config.get("sources", {})

    if src.get("reddit", {}).get("enabled"):
        rf = RedditFetcher()
        subreddits = src["reddit"].get("subreddits", [])
        results.extend(rf.fetch(subreddits=subreddits, limit=src["reddit"].get("limit",5)))

    if src.get("youtube", {}).get("enabled"):
        yf = YouTubeFetcher()
        queries = src["youtube"].get("queries", [])
        results.extend(yf.fetch(queries=queries, limit=src["youtube"].get("limit",5),
                                 api_key=src["youtube"].get("youtube_api_key","")))

    if src.get("x", {}).get("enabled"):
        xf = XFetcher(nitter_instance=src["x"].get("nitter_instance","https://nitter.net"))
        queries = src["x"].get("queries", [])
        results.extend(xf.fetch(queries=queries, limit=src["x"].get("limit",5)))

    if src.get("threads", {}).get("enabled"):
        tf = ThreadsFetcher()
        queries = src["threads"].get("queries", [])
        results.extend(tf.fetch(queries=queries, limit=src["threads"].get("limit",5)))

    return results

def generate_and_speak(config_path="config.yaml"):
    config = load_config(config_path)
    items = collect_all(config)
    script = make_debate_script(items, max_lines=12)
    out_path = config.get("output", {}).get("script_file", "drama_script.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(script)
    # TTS
    if config.get("output", {}).get("tts", True):
        rate_mult = config.get("output", {}).get("tts_rate_multiplier", 1.35)
        voice = config.get("output", {}).get("voice_name", "")
        player = TTSPlayer(rate_multiplier=rate_mult, voice_name=voice)
        # Fast-paced: speak in short chunks
        for chunk in script.split("\n\n"):
            player.speak(chunk, block=True)
            # very short pause between chunks to preserve pace
            import time; time.sleep(0.15)
    return script

if __name__ == "__main__":
    print("Generating drama script...")
    s = generate_and_speak("config.yaml")
    print("--- script written and (optionally) spoken ---")
    print(s)
