# -*- coding: utf-8 -*-
"""
Complete pipeline:

1️⃣  Generate a 145‑second drama script with Gemini‑2.5‑Flash **using live Google‑search grounding**.  
2️⃣  Convert the script to a single‑channel WAV file with Gemini‑3.1‑flash‑tts‑preview.  
3️⃣  **Replace the hand‑crafted timestamps.json** with word‑level timestamps obtained from Groq’s
    `whisper-large-v3-turbo` model.  
4️⃣  Build a video (background clip + subtitles) with MoviePy.  
5️⃣  Upload the final MP4 to Google Drive and optionally publish to YouTube.

Only the Gemini request (step 1) and the timestamp generation (step 3) have been altered.
"""

import os
import re
import json
import struct
import time
import sys
import requests
from datetime import datetime, timezone

# ----------------------------------------------------------------------
# 1️⃣  Environment / constants (unchanged)
# ----------------------------------------------------------------------
YOUTUBE_CLIENT_ID = os.environ["YOUTUBE_CLIENT_ID"]
YOUTUBE_CLIENT_SECRET = os.environ["YOUTUBE_CLIENT_SECRET"]
YOUTUBE_REFRESH_TOKEN = os.environ["YOUTUBE_REFRESH_TOKEN"]
CHANNEL_ID = os.environ.get("YOUTUBE_CHANNEL_ID", "UCKMy8Xqk086_6Kwg5uZoxGw")
GOOGLE_AI_STUDIO_API_KEY = os.environ["GOOGLE_AI_STUDIO_API_KEY"]
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

DRIVE_CLIPS_FOLDER_ID = os.environ["DRIVE_CLIPS_FOLDER_ID"]
DRIVE_MUSIC_FOLDER_ID = os.environ["DRIVE_MUSIC_FOLDER_ID"]
DRIVE_FONT_FILE_ID = os.environ["DRIVE_FONT_FILE_ID"]
DRIVE_EXPORT_FOLDER_ID = os.environ["DRIVE_EXPORT_FOLDER_ID"]

ACTION = os.environ.get("PIPELINE_ACTION", "generate")
STATE_PATH = "state/last_check.json"
ASSETS_DIR = "assets"

HOSTS = {
    "Ryan": {"voice": "Orus", "personality": "mocking, joking, edgy, and completely unimpressed by celebrity privilege"},
    "Katie": {"voice": "Fenrir", "personality": "excited, high-energy, and overly understanding"}
}

# ----------------------------------------------------------------------
# 2️⃣  Helper utilities (unchanged)
# ----------------------------------------------------------------------
def log(msg):
    print(f"[{datetime.now(timezone.utc).isoformat()}] {msg}")

def notify_discord(message):
    if DISCORD_WEBHOOK_URL:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": message[:1900]}, timeout=15)

def build_oauth_credentials():
    from google.oauth2.credentials import Credentials
    return Credentials(
        None,
        refresh_token=YOUTUBE_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=YOUTUBE_CLIENT_ID,
        client_secret=YOUTUBE_CLIENT_SECRET,
    )

def download_drive_folder(drive, folder_id, local_dir, exts):
    os.makedirs(local_dir, exist_ok=True)
    query = f"'{folder_id}' in parents and trashed = false"
    resp = drive.files().list(q=query, fields="files(id, name)").execute()
    for f in resp.get("files", []):
        if f["name"].lower().endswith(tuple(exts)):
            from googleapiclient.http import MediaIoBaseDownload
            with open(os.path.join(local_dir, f["name"]), "wb") as out:
                downloader = MediaIoBaseDownload(out, drive.files().get_media(fileId=f["id"]))
                done = False
                while not done:
                    _, done = downloader.next_chunk()

def agent1_check_velocity(youtube):
    """Return (should_generate, latest_video_title)."""
    playlist_id = (
        youtube.channels()
        .list(part="contentDetails", id=CHANNEL_ID)
        .execute()["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    )
    latest = (
        youtube.playlistItems()
        .list(part="snippet", playlistId=playlist_id, maxResults=1)
        .execute()["items"][0]
    )
    video_id = latest["snippet"]["resourceId"]["videoId"]
    video_title = latest["snippet"]["title"]
    views_now = int(
        youtube.videos()
        .list(part="statistics", id=video_id)
        .execute()["items"][0]["statistics"]
        .get("viewCount", 0)
    )

    if not os.path.exists(STATE_PATH):
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        with open(STATE_PATH, "w") as f:
            json.dump({video_id: views_now}, f)
        return True, video_title

    with open(STATE_PATH, "r") as f:
        prev_data = json.load(f)

    last_views = prev_data.get(video_id, 0)
    hourly_delta = views_now - last_views

    with open(STATE_PATH, "w") as f:
        json.dump({video_id: views_now}, f)

    # If the view count is growing slower than 60 per hour we consider it “flat‑lined”.
    return hourly_delta < 60, video_title

# ----------------------------------------------------------------------
# 3️⃣  Core pipeline – generate_assets()
# ----------------------------------------------------------------------
def generate_assets(youtube, youtube_analytics, drive, client):
    """Generate script → TTS → timestamps → video → upload."""
    today = datetime.now(timezone.utc).date().isoformat()

    # ---------- Audience analytics (unchanged) ----------
    age_gender = (
        youtube_analytics.reports()
        .query(
            ids=f"channel=={CHANNEL_ID}",
            startDate="2020-01-01",
            endDate=today,
            metrics="viewerPercentage",
            dimensions="ageGroup,gender",
            sort="-viewerPercentage",
        )
        .execute()
        .get("rows", [])
    )

    country = (
        youtube_analytics.reports()
        .query(
            ids=f"channel=={CHANNEL_ID}",
            startDate="2020-01-01",
            endDate=today,
            metrics="views",
            dimensions="country",
            sort="-views",
        )
        .execute()
        .get("rows", [])
    )

    age_gender_summary = "\n".join([f"{r[0]} {r[1]}: {r[2]:.1f}%" for r in age_gender[:5]])
    country_summary = "\n".join([f"{r[0]}: {r[1]} views" for r in country[:5]])
    demo_summary = f"Age/Gender:\n{age_gender_summary}\n\nTop Countries:\n{country_summary}"

    # ---------- Prompt (unchanged) ----------
    prompt = (
        f"Find trending internet or celebrity drama matching this audience:\n{demo_summary}\n"
        f"Write a long 145-second YouTube Short script alternating between Ryan ({HOSTS['Ryan']['personality']}) "
        f"and Katie ({HOSTS['Katie']['personality']}). Make fun of the absolute absurdity of the influencers involved. "
        f"Format exactly as TITLE: <title> \\n --- \\n Dialogue starting with names."
    )

    # ---------- 1️⃣ Gemini script generation with **live web search grounding** ----------
    # The Google‑search tool forces Gemini to pull the latest factual data before answering.
    from google.genai import types

    search_tool = types.Tool(google_search=types.GoogleSearchTool())
    grounding_config = types.GenerateContentConfig(tools=[search_tool])

    resp = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        generation_config=grounding_config,   # <-- live search enabled
    )
    raw_text = resp.text.strip()

    # Extract title & script body (unchanged)
    title_match = re.search(r"TITLE:\s*(.+?)\s*\n", raw_text)
    title = title_match.group(1) if title_match else "Trending Drama"
    script = raw_text.split("---")[-1].strip()

    # ---------- TTS via Gemini 3.1‑flash‑tts‑preview (unchanged) ----------
    from google.genai import types as genai_types

    tts_config = genai_types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=genai_types.SpeechConfig(
            multi_speaker_voice_config=genai_types.MultiSpeakerVoiceConfig(
                speaker_voice_configs=[
                    genai_types.SpeakerVoiceConfig(
                        speaker="Ryan",
                        voice_config=genai_types.VoiceConfig(
                            prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(
                                voice_name=HOSTS["Ryan"]["voice"]
                            )
                        ),
                    ),
                    genai_types.SpeakerVoiceConfig(
                        speaker="Katie",
                        voice_config=genai_types.VoiceConfig(
                            prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(
                                voice_name=HOSTS["Katie"]["voice"]
                            )
                        ),
                    ),
                ]
            )
        ),
    )

    audio_resp = client.models.generate_content(
        model="gemini-3.1-flash-tts-preview",
        contents=script,
        config=tts_config,
    )
    raw_pcm = audio_resp.candidates[0].content.parts[0].inline_data.data

    # Write a simple 24‑kHz mono WAV file (unchanged)
    wav_header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + len(raw_pcm),
        b"WAVE",
        b"fmt ",
        16,
        1,
        1,
        24000,
        48000,
        2,
        16,
        b"data",
        len(raw_pcm),
    )
    audio_path = "voice.wav"
    with open(audio_path, "wb") as f:
        f.write(wav_header + raw_pcm)

    # ------------------------------------------------------------------
    # 2️⃣  **Replace handcrafted timestamps** with Groq Whisper word timestamps
    # ------------------------------------------------------------------
    # Groq API key is read from the same environment‑var pattern used elsewhere.
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY environment variable not set")

    import groq

    groq_client = groq.Client(api_key=GROQ_API_KEY)

    def whisper_transcribe_with_retry(path, max_retries=3, backoff=2):
        """
        Call Groq Whisper. Retries on rate‑limit; any other error falls back
        to a “no timestamps” mode.
        """
        for attempt in range(1, max_retries + 1):
            try:
                with open(path, "rb") as audio_file:
                    return groq_client.audio.transcriptions.create(
                        model="whisper-large-v3-turbo",
                        file=audio_file,
                        response_format="json",
                        timestamp_granularities=["word"],
                    )
            except groq.RateLimitError:
                if attempt == max_retries:
                    raise
                log(f"Rate‑limit hit on Whisper (attempt {attempt}); sleeping…")
                time.sleep(backoff * attempt)
            except Exception as exc:  # any other failure → graceful degrade
                log(f"Whisper transcription failed ({exc}); proceeding without subtitles.")
                return None

    whisper_resp = whisper_transcribe_with_retry(audio_path)

    if whisper_resp:
        # Whisper returns a dict with a "words" list: each element has `word`, `start`, `end`
        words = [
            {"word": w["word"], "start": w["start"], "end": w["end"]}
            for w in whisper_resp.get("words", [])
        ]
    else:
        words = []  # fallback – no subtitle overlay

    # ------------------------------------------------------------------
    # 3️⃣  Asset download (unchanged)
    # ------------------------------------------------------------------
    clips_dir, music_dir, font_path = "clips", "music", "font.ttf"
    download_drive_folder(drive, DRIVE_CLIPS_FOLDER_ID, clips_dir, (".mp4", ".mov"))
    download_drive_folder(drive, DRIVE_MUSIC_FOLDER_ID, music_dir, (".mp3", ".wav"))

    # Font file (unchanged)
    font_files = (
        drive.files()
        .list(q=f"'{DRIVE_FONT_FILE_ID}' in parents")
        .execute()
        .get("files", [])
    )
    if font_files:
        with open(font_path, "wb") as out:
            out.write(drive.files().get_media(fileId=font_files[0]["id"]).execute())

    # ------------------------------------------------------------------
    # 4️⃣  Video construction (unchanged apart from using `words` from Whisper)
    # ------------------------------------------------------------------
    from PIL import Image

    # Compatibility shim for Pillow ≥10
    if not hasattr(Image, "ANTIALIAS"):
        Image.ANTIALIAS = Image.Resampling.LANCZOS

    from moviepy.editor import (
        AudioFileClip,
        VideoFileClip,
        TextClip,
        CompositeVideoClip,
    )
    import moviepy.video.fx.all as vfx

    voice = AudioFileClip(audio_path)
    # Pick the first clip found in the downloaded folder as background
    bg_raw = (
    if DISCORD_WEBHOOK_URL:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": message[:1900]}, timeout=15)

def build_oauth_credentials():
    from google.oauth2.credentials import Credentials
    return Credentials(
        None, refresh_token=YOUTUBE_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=YOUTUBE_CLIENT_ID, client_secret=YOUTUBE_CLIENT_SECRET
    )

def download_drive_folder(drive, folder_id, local_dir, exts):
    os.makedirs(local_dir, exist_ok=True)
    query = f"'{folder_id}' in parents and trashed = false"
    resp = drive.files().list(q=query, fields="files(id, name)").execute()
    for f in resp.get("files", []):
        if f["name"].lower().endswith(tuple(exts)):
            from googleapiclient.http import MediaIoBaseDownload
            with open(os.path.join(local_dir, f["name"]), "wb") as out:
                downloader = MediaIoBaseDownload(out, drive.files().get_media(fileId=f["id"]))
                done = False
                while not done:
                    _, done = downloader.next_chunk()

def agent1_check_velocity(youtube):
    playlist_id = youtube.channels().list(part="contentDetails", id=CHANNEL_ID).execute()["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    latest = youtube.playlistItems().list(part="snippet", playlistId=playlist_id, maxResults=1).execute()["items"][0]
    video_id, video_title = latest["snippet"]["resourceId"]["videoId"], latest["snippet"]["title"]
    views_now = int(youtube.videos().list(part="statistics", id=video_id).execute()["items"][0]["statistics"].get("viewCount", 0))
    
    if not os.path.exists(STATE_PATH):
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        with open(STATE_PATH, "w") as f:
            json.dump({video_id: views_now}, f)
        return True, video_title

    with open(STATE_PATH, "r") as f:
        prev_data = json.load(f)
    
    last_views = prev_data.get(video_id, 0)
    hourly_delta = views_now - last_views
    
    with open(STATE_PATH, "w") as f:
        json.dump({video_id: views_now}, f)
        
    return hourly_delta < 60, video_title

def generate_assets(youtube, youtube_analytics, drive, client):
    today = datetime.now(timezone.utc).date().isoformat()

    age_gender = youtube_analytics.reports().query(
        ids=f"channel=={CHANNEL_ID}", startDate="2020-01-01", endDate=today,
        metrics="viewerPercentage", dimensions="ageGroup,gender", sort="-viewerPercentage"
    ).execute().get("rows", [])

    country = youtube_analytics.reports().query(
        ids=f"channel=={CHANNEL_ID}", startDate="2020-01-01", endDate=today,
        metrics="views", dimensions="country", sort="-views"
    ).execute().get("rows", [])

    age_gender_summary = "\n".join([f"{r[0]} {r[1]}: {r[2]:.1f}%" for r in age_gender[:5]])
    country_summary = "\n".join([f"{r[0]}: {r[1]} views" for r in country[:5]])
    demo_summary = f"Age/Gender:\n{age_gender_summary}\n\nTop Countries:\n{country_summary}"

    # Prompt updated to specifically generate 145 seconds of content
    prompt = f"Find trending internet or celebrity drama matching this audience:\n{demo_summary}\nWrite a long 145-second YouTube Short script alternating between Ryan ({HOSTS['Ryan']['personality']}) and Katie ({HOSTS['Katie']['personality']}). Make fun of the absolute absurdity of the influencers involved. Format exactly as TITLE: <title> \\n --- \\n Dialogue starting with names."
    resp = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
    raw_text = resp.text.strip()
    
    title = re.search(r"TITLE:\s*(.+?)\s*\n", raw_text).group(1) if "TITLE:" in raw_text else "Trending Drama"
    script = raw_text.split("---")[-1].strip()

    from google.genai import types
    config = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            multi_speaker_voice_config=types.MultiSpeakerVoiceConfig(
                speaker_voice_configs=[
                    types.SpeakerVoiceConfig(speaker="Ryan", voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=HOSTS["Ryan"]["voice"]))),
                    types.SpeakerVoiceConfig(speaker="Katie", voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=HOSTS["Katie"]["voice"])))
                ]
            )
        )
    )
    audio_resp = client.models.generate_content(model="gemini-3.1-flash-tts-preview", contents=script, config=config)
    raw_pcm = audio_resp.candidates[0].content.parts[0].inline_data.data
    
    wav_header = struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(raw_pcm), b"WAVE", b"fmt ", 16, 1, 1, 24000, 48000, 2, 16, b"data", len(raw_pcm))
    audio_path = "voice.wav"
    with open(audio_path, "wb") as f:
        f.write(wav_header + raw_pcm)

    ts_prompt = "Analyze this script and output a valid JSON array of objects for word timestamps. Each object must have exactly keys 'word', 'start' (float seconds), and 'end' (float seconds) mapping the timeline of the text perfectly:\n" + script
    ts_resp = client.models.generate_content(model="gemini-2.5-flash", contents=ts_prompt)
    clean_json = re.search(r"\[.*\]", ts_resp.text, re.DOTALL).group(0)
    with open("timestamps.json", "w") as f:
        f.write(clean_json)

    clips_dir, music_dir, font_path = "clips", "music", "font.ttf"
    download_drive_folder(drive, DRIVE_CLIPS_FOLDER_ID, clips_dir, (".mp4", ".mov"))
    download_drive_folder(drive, DRIVE_MUSIC_FOLDER_ID, music_dir, (".mp3", ".wav"))
    
    font_files = drive.files().list(q=f"'{DRIVE_FONT_FILE_ID}' in parents").execute().get("files", [])
    if font_files:
        with open(font_path, "wb") as out:
            out.write(drive.files().get_media(fileId=font_files[0]["id"]).execute())

    from PIL import Image
    if not hasattr(Image, "ANTIALIAS"): Image.ANTIALIAS = Image.Resampling.LANCZOS
    from moviepy.editor import AudioFileClip, VideoFileClip, TextClip, concatenate_videoclips, CompositeAudioClip, CompositeVideoClip
    import moviepy.video.fx.all as vfx

    voice = AudioFileClip(audio_path)
    bg_raw = VideoFileClip(os.path.join(clips_dir, os.listdir(clips_dir)[0])).without_audio().fx(vfx.speedx, 1.5)
    
    # Automatically loops video asset if shorter than the audio pipeline duration
    if bg_raw.duration < voice.duration:
        bg_clip = bg_raw.fx(vfx.loop, duration=voice.duration)
    else:
        bg_clip = bg_raw.subclip(0, voice.duration)
    
    text_clips = [bg_clip]
    with open("timestamps.json") as f:
        words = json.loads(f.read())
    for w in words:
        txt = TextClip(w["word"], fontsize=75, color="yellow", font=font_path, stroke_color="black", stroke_width=3, method="label")
        text_clips.append(txt.set_start(w["start"]).set_end(w["end"]).set_position(("center", "center")))

    video_path = "output.mp4"
    CompositeVideoClip(text_clips).set_audio(voice).write_videofile(video_path, fps=30, codec="libx264", audio_codec="aac")

    from googleapiclient.http import MediaFileUpload
    meta = {"name": f"Short_{int(time.time())}.mp4", "parents": [DRIVE_EXPORT_FOLDER_ID]}
    media = MediaFileUpload(video_path, mimetype="video/mp4")
    drive_file = drive.files().create(body=meta, media_body=media, fields="webViewLink").execute()
    
    notify_discord(f"🚨 **New 3-Minute Short Ready!**\nDrive Link: {drive_file.get('webViewLink')}\n\nRun 'publish' phase to push live.")

def publish_video(youtube):
    video_path = "output.mp4"
    if not os.path.exists(video_path):
        notify_discord("❌ Cannot publish: Local output.mp4 file not found.")
        return
        
    from googleapiclient.http import MediaFileUpload
    body = {
        "snippet": {"title": "Viral Celebrity Drama Exposed! #Shorts", "description": "Breaking down the latest Hollywood or influencer trainwreck.\n\n#shorts #drama", "categoryId": "24"},
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False}
    }
    media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    
    response = None
    while response is None:
        _, response = request.next_chunk()
        
    notify_discord(f"🚀 **Published directly to YouTube!**\nLink: https://youtube.com/shorts/{response.get('id')}")

def main():
    import googleapiclient.discovery
    from google import genai
    
    creds = build_oauth_credentials()
    youtube = googleapiclient.discovery.build("youtube", "v3", credentials=creds)
    youtube_analytics = googleapiclient.discovery.build("youtubeAnalytics", "v2", credentials=creds)
    drive = googleapiclient.discovery.build("drive", "v3", credentials=creds)
    client = genai.Client(api_key=GOOGLE_AI_STUDIO_API_KEY)
    
    if ACTION == "generate":
        flatlined, title = agent1_check_velocity(youtube)
        if not flatlined:
            log(f"Velocity stable for {title}. Exiting.")
            return
        generate_assets(youtube, youtube_analytics, drive, client)
    elif ACTION == "publish":
        publish_video(youtube)

if __name__ == "__main__":
    main()

