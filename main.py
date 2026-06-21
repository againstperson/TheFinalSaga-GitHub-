# -*- coding: utf-8 -*-
import os
import re
import json
import random
import struct
import time
import sys
from datetime import datetime, timezone
import requests

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

def log(msg):
    print(f"[{datetime.now(timezone.utc).isoformat()}] {msg}")

def notify_discord(message):
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
        metrics="viewerPercentage", dimensions="country", sort="-viewerPercentage"
    ).execute().get("rows", [])

    age_gender_summary = "\n".join([f"{r[0]} {r[1]}: {r[2]:.1f}%" for r in age_gender[:5]])
    country_summary = "\n".join([f"{r[0]}: {r[1]:.1f}%" for r in country[:5]])
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

