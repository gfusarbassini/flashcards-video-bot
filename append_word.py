import pandas as pd
import sys
import os
import io
import requests
import tempfile
import cairosvg
from google import genai
from google.genai import types
from gtts import gTTS
from pydub import AudioSegment
from moviepy.video.VideoClip import ImageClip
from moviepy.video.compositing.concatenate import concatenate_videoclips
from ftplib import FTP

# --- CONFIGURAZIONE ---
CSV_FILE = "parole.csv"
BASI_DIR = "flashcards/BASI"
ASSET_DIR = "flashcards/ASSET"
os.makedirs(ASSET_DIR, exist_ok=True)

FTP_HOST = "ftp.roadtominds.altervista.org"
FTP_USER = "roadtominds"
FTP_PASS = os.getenv("FTP_PASSWORD")
FTP_DIR = "Flashcards"

# --- FUNZIONI VIDEO ---
def wrap_text(text, width=36):
    words = text.split()
    lines, line = [], []
    char_count = 0
    for word in words:
        if char_count + len(word) + (1 if line else 0) <= width:
            line.append(word)
            char_count += len(word) + (1 if line else 0)
        else:
            lines.append(" ".join(line))
            line = [word]
            char_count = len(word)
    if line: lines.append(" ".join(line))
    tspans = []
    for i, l in enumerate(lines):
        dy = "0em" if i == 0 else "1.2em"
        tspans.append(f'<tspan x="118.18359" dy="{dy}">{l}</tspan>')
    return "".join(tspans)

def crea_video(parola, trad, nota_es_wrapped, base_file, out_video):
    clips = []
    with open(base_file, "r", encoding="utf-8") as f:
        svg_template = f.read()

    def get_frame(p, t, n, duration):
        svg = svg_template.replace("PAROLAPAROLAPAROLA", p)
        svg = svg.replace("TRADUZIONETRADUZIONETRADUZIONE", t)
        svg = svg.replace("NOTAESEMPIO", n)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            cairosvg.svg2png(bytestring=svg.encode("utf-8"), write_to=tmp.name)
            return ImageClip(tmp.name).set_duration(duration)

    # 1s Traduzione | 5s Countdown | 5s Finale
    clips.append(get_frame("", trad, "", 1))
    for i in range(5, 0, -1):
        clips.append(get_frame("", trad, str(i), 1))
    clips.append(get_frame(parola, trad, nota_es_wrapped, 5))

    video = concatenate_videoclips(clips, method="compose")
    video.write_videofile(out_video, fps=24, codec="libx264", audio=False)

# --- FUNZIONI TELEGRAM & AUDIO ---
def send_telegram(chat_id, text, voice_path, token):
    base_url = f"https://api.telegram.org/bot{token}"
    requests.post(f"{base_url}/sendMessage", json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})
    with open(voice_path, 'rb') as v:
        requests.post(f"{base_url}/sendVoice", data={'chat_id': chat_id}, files={'voice': v})

def genera_audio(parola_russa, output_ogg):
    temp_mp3 = "temp.mp3"
    tts = gTTS(text=f"{parola_russa}... {parola_russa}... {parola_russa}", lang='ru')
    tts.save(temp_mp3)
    audio = AudioSegment.from_file(temp_mp3)
    rallentato = audio._spawn(audio.raw_data, overrides={'frame_rate': int(audio.frame_rate * 0.75)})
    rallentato.set_frame_rate(audio.frame_rate).export(output_ogg, format="ogg", codec="libopus")

# --- CORE LOGIC ---
def generate_csv_record(input_word):
    client = genai.Client(api_key=os.getenv('GEMINI_API_KEY'))
    prompt = f"Analizza: '{input_word}'. Rispondi SOLO con una riga CSV: Parola(RU),Traduzione(IT),Spiegazione,Nota,Esempio,"
    response = client.models.generate_content(model='gemini-3-flash-preview', contents=prompt)
    return response.text.strip().replace('```csv', '').replace('```', '').split('\n')[0]

if __name__ == "__main__":
    if len(sys.argv) < 2: sys.exit(1)
    
    input_word = sys.argv[1]
    chat_id = sys.argv[2] if len(sys.argv) > 2 else None
    bot_token = os.getenv("TELEGRAM_TOKEN")

    # 1. Gemini
    line = generate_csv_record(input_word)
    cols = ['Parola', 'Traduzione', 'Spiegazione', 'Nota', 'Esempio', 'FileVideo']
    new_row = pd.read_csv(io.StringIO(line), header=None, names=cols, quotechar='"', skipinitialspace=True).fillna('')
    
    parola_ru = str(new_row['Parola'].iloc[0])
    trad_it = str(new_row['Traduzione'].iloc[0])

    # 2. Audio & Telegram
    genera_audio(parola_ru, "voice.ogg")
    if chat_id and bot_token:
        msg = f"🇷🇺 *{parola_ru}*\n🇮🇹 {trad_it}\n\n📖 {new_row['Spiegazione'].iloc[0]}\n💬 {new_row['Esempio'].iloc[0]}"
        send_telegram(chat_id, msg, "voice.ogg", bot_token)

    # 3. Video & FTP
    nota_wrap = wrap_text(f"{new_row['Nota'].iloc[0]} {new_row['Esempio'].iloc[0]}")
    video_path = os.path.join(ASSET_DIR, f"{parola_ru}.mp4")
    crea_video(parola_ru, trad_it, nota_wrap, os.path.join(BASI_DIR, "base_frame3.svg"), video_path)
    
    with FTP(FTP_HOST, FTP_USER, FTP_PASS) as ftp:
        ftp.cwd(FTP_DIR)
        with open(video_path, "rb") as f:
            ftp.storbinary(f"STOR {parola_ru}.mp4", f)

    # 4. Save CSV
    df = pd.read_csv(CSV_FILE) if os.path.exists(CSV_FILE) else pd.DataFrame(columns=cols)
    pd.concat([df, new_row], ignore_index=True).to_csv(CSV_FILE, index=False)
