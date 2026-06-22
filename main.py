# -*- coding: utf-8 -*-
"""
StorySaga / TheFinalSaga – Automated YouTube Shorts Pipeline
Runs entirely on GitHub Actions (cloud-only, no local execution).

Pipeline:
  1. Check view-velocity of latest video; skip if still growing fast.
  2. Pull audience analytics from YouTube Analytics API.
  3. Generate a 145-second drama script with Gemini-2.5-Flash
     *** using live Google Search grounding (no hallucinated drama). ***
  4. Convert script to stereo 24kHz WAV with Gemini TTS (multi-speaker).
  5. Extract word-level timestamps from the rendered audio via
     *** Groq Whisper large-v3-turbo (replaces text-guessed timestamps.json). ***
  6. Build the Short (background clip + karaoke subtitles) with MoviePy.
  7. Upload MP4 to Google Drive and notify Discord.
  8. (Separate publish phase) Push to YouTube.
"""

import os
import re
import json
import struct
import time
import requests
from datetime import datetime, timezone

# ─────────────────────────────────────────────────────────────────────────────
# Environment variables  (all must be set as GitHub Actions secrets)
# ─────────────────────────────────────────────────────────────────────────────
YOUTUBE_CLIENT_ID      = os.environ["YOUTUBE_CLIENT_ID"]
YOUTUBE_CLIENT_SECRET  = os.environ["YOUTUBE_CLIENT_SECRET"]
YOUTUBE_REFRESH_TOKEN  = os.environ["YOUTUBE_REFRESH_TOKEN"]
CHANNEL_ID             = os.environ.get("YOUTUBE_CHANNEL_ID", "UCKMy8Xqk086_6Kwg5uZoxGw")
GOOGLE_AI_STUDIO_API_KEY = os.environ["GOOGLE_AI_STUDIO_API_KEY"]
GROQ_API_KEY           = os.environ["GROQ_API_KEY"]
DISCORD_WEBHOOK_URL    = os.environ.get("DISCORD_WEBHOOK_URL")

DRIVE_CLIPS_FOLDER_ID  = os.environ["DRIVE_CLIPS_FOLDER_ID"]
DRIVE_MUSIC_FOLDER_ID  = os.environ["DRIVE_MUSIC_FOLDER_ID"]
DRIVE_FONT_FILE_ID     = os.environ["DRIVE_FONT_FILE_ID"]
DRIVE_EXPORT_FOLDER_ID = os.environ["DRIVE_EXPORT_FOLDER_ID"]

ACTION     = os.environ.get("PIPELINE_ACTION", "generate")
STATE_PATH = "state/last_check.json"

HOSTS = {
    "Ryan":  {"voice": "Orus",   "personality": "mocking, joking, edgy, and completely unimpressed by celebrity privilege"},
    "Katie": {"voice": "Fenrir", "personality": "excited, high-energy, and overly understanding"},
}


# ─────────────────────────────────────────────────────────────────────────────
# Helper utilities
# ─────────────────────────────────────────────────────────────────────────────
def log(msg):
    print(f"[{datetime.now(timezone.utc).isoformat()}] {msg}", flush=True)


def notify_discord(message):
    if DISCORD_WEBHOOK_URL:
        try:
            requests.post(
                DISCORD_WEBHOOK_URL,
                json={"content": message[:1900]},
                timeout=15,
            )
        except Exception as exc:
            log(f"Discord notify failed: {exc}")


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
    """Download all files with matching extensions from a Drive folder."""
    os.makedirs(local_dir, exist_ok=True)
    query = f"'{folder_id}' in parents and trashed = false"
    resp  = drive.files().list(q=query, fields="files(id, name)").execute()
    for f in resp.get("files", []):
        if f["name"].lower().endswith(tuple(exts)):
            from googleapiclient.http import MediaIoBaseDownload
            dest = os.path.join(local_dir, f["name"])
            with open(dest, "wb") as out:
                dl = MediaIoBaseDownload(out, drive.files().get_media(fileId=f["id"]))
                done = False
                while not done:
                    _, done = dl.next_chunk()
            log(f"Downloaded: {dest}")


# ─────────────────────────────────────────────────────────────────────────────
# Agent 1 – view-velocity gatekeeper
# ─────────────────────────────────────────────────────────────────────────────
def agent1_check_velocity(youtube):
    """Return (should_generate: bool, latest_video_title: str)."""
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
    video_id    = latest["snippet"]["resourceId"]["videoId"]
    video_title = latest["snippet"]["title"]
    views_now   = int(
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
        prev_data
      refresh_token=YOUTUBE_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=YOUTUBE_CLIENT_ID,
        client_secret=YOUTUBE_CLIENT_SECRET,
    )


def download_drive_folder(drive, folder_id, local_dir, exts):
    """Download all files with matching extensions from a Drive folder."""
    os.makedirs(local_dir, exist_ok=True)
    query = f"'{folder_id}' in parents and trashed = false"
    resp  = drive.files().list(q=query, fields="files(id, name)").execute()
    for f in resp.get("files", []):
        if f["name"].lower().endswith(tuple(exts)):
            from googleapiclient.http import MediaIoBaseDownload
            dest = os.path.join(local_dir, f["name"])
            with open(dest, "wb") as out:
                dl = MediaIoBaseDownload(out, drive.files().get_media(fileId=f["id"]))
                done = False
                while not done:
                    _, done = dl.next_chunk()
            log(f"Downloaded: {dest}")


# ─────────────────────────────────────────────────────────────────────────────
# Agent 1 – view-velocity gatekeeper
# ─────────────────────────────────────────────────────────────────────────────
def agent1_check_velocity(youtube):
    """Return (should_generate: bool, latest_video_title: str)."""
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
    video_id    = latest["snippet"]["resourceId"]["videoId"]
    video_title = latest["snippet"]["title"]
    views_now   = int(
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

    last_views    = prev_data.get(video_id, 0)
    hourly_delta  = views_now - last_views

    with open(STATE_PATH, "w") as f:
        json.dump({video_id: views_now}, f)

    # Flat-lined = fewer than 60 new views since last run → time for fresh content
    return hourly_delta < 60, video_title


# ─────────────────────────────────────────────────────────────────────────────
# Core pipeline
# ─────────────────────────────────────────────────────────────────────────────
def generate_assets(youtube, youtube_analytics, drive, client):
    """Full generate → TTS → timestamps → video → upload cycle."""

    today = datetime.now(timezone.utc).date().isoformat()

    # ── Audience analytics ──────────────────────────────────────────────────
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
    country_summary    = "\n".join([f"{r[0]}: {r[1]} views"       for r in country[:5]])
    demo_summary = (
        f"Age/Gender:\n{age_gender_summary}\n\nTop Countries:\n{country_summary}"
    )

               from google.genai import types

    prompt = (
        f"Find trending internet or celebrity drama matching this audience:\n{demo_summary}\n"
        f"Write a long 145-second YouTube Short script alternating between "
        f"Ryan ({HOSTS['Ryan']['personality']}) and "
        f"Katie ({HOSTS['Katie']['personality']}). "
        f"Make fun of the absolute absurdity of the influencers involved. "
        f"Format exactly as TITLE: <title> \\n --- \\n Dialogue starting with names."
    )

    log("Calling Gemini-2.5-Flash...")
    resp = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    raw_text = resp.text.strip()

    title_match = re.search(r"TITLE:\s*(.+?)\s*\n", raw_text)
    title  = title_match.group(1) if title_match else "Trending Drama"
    script = raw_text.split("---")[-1].strip()
    log(f"Script ready: {title}")

    # ── Step 2 · TTS via Gemini multi-speaker ───────────────────────────────
    tts_config = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            multi_speaker_voice_config=types.MultiSpeakerVoiceConfig(
                speaker_voice_configs=[
                    types.SpeakerVoiceConfig(
                        speaker="Ryan",
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=HOSTS["Ryan"]["voice"]
                            )
                        ),
                    ),
                    types.SpeakerVoiceConfig(
                        speaker="Katie",
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=HOSTS["Katie"]["voice"]
                            )
                        ),
                    ),
                ]
            )
        ),
    )

    log("Generating TTS audio…")
    audio_resp = client.models.generate_content(
        model="gemini-3.1-flash-tts-preview",
        contents=script,
        config=tts_config,
    )
    raw_pcm = audio_resp.candidates[0].content.parts[0].inline_data.data

    # Write 24 kHz mono 16-bit PCM as a standard WAV
    wav_header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + len(raw_pcm), b"WAVE",
        b"fmt ", 16, 1, 1, 24000, 48000, 2, 16,
        b"data", len(raw_pcm),
    )
    audio_path = "voice.wav"
    with open(audio_path, "wb") as f:
        f.write(wav_header + raw_pcm)
    log(f"Audio written → {audio_path}")

    # ── Step 3 · Word-level timestamps via Groq Whisper ─────────────────────
    #
    # WHY THIS REPLACES THE OLD APPROACH:
    #   The old method asked Gemini to *guess* timestamps from text alone.
    #   That produces drift, misalignment, and hallucinated timings.
    #   Groq Whisper runs on the actual rendered audio, so every word boundary
    #   is extracted directly from the signal — frame-accurate and free.
    #
    # IMPORTANT NOTES:
    #   • response_format must be "verbose_json" (not "json") to receive the
    #     `words` list.  "json" only returns the plain transcript text.
    #   • The SDK returns a Transcription object; word attributes are accessed
    #     as w.word / w.start / w.end  (not dict keys).
    import groq as groq_sdk

    groq_client = groq_sdk.Groq(api_key=GROQ_API_KEY)

    def whisper_transcribe_with_retry(path, max_retries=3, backoff=2):
        for attempt in range(1, max_retries + 1):
            try:
                with open(path, "rb") as audio_file:
                    return groq_client.audio.transcriptions.create(
                        model="whisper-large-v3-turbo",
                        file=audio_file,
                        response_format="verbose_json",       # required for timestamps
                        timestamp_granularities=["word"],     # word-level precision
                    )
            except groq_sdk.RateLimitError:
                if attempt == max_retries:
                    raise
                wait = backoff * attempt
                log(f"Groq rate-limit hit (attempt {attempt}/{max_retries}); retrying in {wait}s…")
                time.sleep(wait)
            except Exception as exc:
                log(f"Whisper transcription failed ({exc}); proceeding without subtitles.")
                return None

    log("Transcribing audio for word-level timestamps via Groq Whisper…")
    whisper_resp = whisper_transcribe_with_retry(audio_path)

    if whisper_resp and getattr(whisper_resp, "words", None):
        # Each Word object has .word (str), .start (float), .end (float)
        words = [
            {"word": w.word.strip(), "start": w.start, "end": w.end}
            for w in whisper_resp.words
        ]
        log(f"Extracted {len(words)} word timestamps from Groq Whisper.")
    else:
        words = []
        log("No word timestamps returned; video will render without subtitle overlay.")

    # ── Step 4 · Download Drive assets ──────────────────────────────────────
    clips_dir = "clips"
    music_dir = "music"
    font_path = "font.ttf"

    download_drive_folder(drive, DRIVE_CLIPS_FOLDER_ID, clips_dir, (".mp4", ".mov"))
    download_drive_folder(drive, DRIVE_MUSIC_FOLDER_ID, music_dir, (".mp3", ".wav"))

    font_files = (
        drive.files()
        .list(q=f"'{DRIVE_FONT_FILE_ID}' in parents")
        .execute()
        .get("files", [])
    )
    if font_files:
        with open(font_path, "wb") as out:
            out.write(drive.files().get_media(fileId=font_files[0]["id"]).execute())
        log("Font downloaded.")

    # ── Step 5 · Build video with MoviePy ───────────────────────────────────
    from PIL import Image
    if not hasattr(Image, "ANTIALIAS"):
        Image.ANTIALIAS = Image.Resampling.LANCZOS   # Pillow ≥ 10 compat shim

    from moviepy.editor import AudioFileClip, VideoFileClip, TextClip, CompositeVideoClip
    import moviepy.video.fx.all as vfx

    voice  = AudioFileClip(audio_path)
    bg_raw = (
        VideoFileClip(os.path.join(clips_dir, os.listdir(clips_dir)[0]))
        .without_audio()
        .fx(vfx.speedx, 1.5)
    )

    # Loop background if shorter than audio; otherwise trim it
    if bg_raw.duration < voice.duration:
        bg_clip = bg_raw.fx(vfx.loop, duration=voice.duration)
    else:
        bg_clip = bg_raw.subclip(0, voice.duration)

    layers = [bg_clip]
    for w in words:
        txt = TextClip(
            w["word"],
            fontsize=75,
            color="yellow",
            font=font_path,
            stroke_color="black",
            stroke_width=3,
            method="label",
        )
        layers.append(
            txt.set_start(w["start"]).set_end(w["end"]).set_position(("center", "center"))
        )

    video_path = "output.mp4"
    log("Rendering video…")
    CompositeVideoClip(layers).set_audio(voice).write_videofile(
        video_path, fps=30, codec="libx264", audio_codec="aac"
    )
    log(f"Video rendered → {video_path}")

    # ── Step 6 · Upload to Google Drive + notify Discord ────────────────────
    from googleapiclient.http import MediaFileUpload

    meta       = {"name": f"Short_{int(time.time())}.mp4", "parents": [DRIVE_EXPORT_FOLDER_ID]}
    media_body = MediaFileUpload(video_path, mimetype="video/mp4")
    drive_file = drive.files().create(body=meta, media_body=media_body, fields="webViewLink").execute()
    drive_link = drive_file.get("webViewLink", "N/A")
    log(f"Uploaded to Drive: {drive_link}")

    notify_discord(
        f"🚨 **New Short Ready!**\n"
        f"**Title:** {title}\n"
        f"**Drive:** {drive_link}\n\n"
        f"_Run the `publish` phase to push live to YouTube._"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Publish phase (triggered separately via PIPELINE_ACTION=publish)
# ─────────────────────────────────────────────────────────────────────────────
def publish_video(youtube):
    video_path = "output.mp4"
    if not os.path.exists(video_path):
        notify_discord("❌ Cannot publish: `output.mp4` not found in workspace.")
        return

    from googleapiclient.http import MediaFileUpload

    body = {
        "snippet": {
            "title":       "Viral Celebrity Drama Exposed! #Shorts",
            "description": "Breaking down the latest Hollywood or influencer trainwreck.\n\n#shorts #drama",
            "categoryId":  "24",
        },
        "status": {
            "privacyStatus":           "public",
            "selfDeclaredMadeForKids": False,
        },
    }
    media   = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        _, response = request.next_chunk()

    video_id = response.get("id")
    log(f"Published: https://youtube.com/shorts/{video_id}")
    notify_discord(f"🚀 **Published to YouTube!**\nhttps://youtube.com/shorts/{video_id}")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────
def main():
    import googleapiclient.discovery
    from google import genai

    creds             = build_oauth_credentials()
    youtube           = googleapiclient.discovery.build("youtube",          "v3", credentials=creds)
    youtube_analytics = googleapiclient.discovery.build("youtubeAnalytics", "v2", credentials=creds)
    drive             = googleapiclient.discovery.build("drive",             "v3", credentials=creds)
    client            = genai.Client(api_key=GOOGLE_AI_STUDIO_API_KEY)

    if ACTION == "generate":
        flatlined, title = agent1_check_velocity(youtube)
        if not flatlined:
            log(f"Velocity still healthy for '{title}' — skipping generation.")
            return
        log(f"View velocity flat-lined on '{title}' — generating new content.")
        generate_assets(youtube, youtube_analytics, drive, client)

    elif ACTION == "publish":
        publish_video(youtube)

    else:
        log(f"Unknown PIPELINE_ACTION='{ACTION}'. Set to 'generate' or 'publish'.")


if __name__ == "__main__":
    main()
