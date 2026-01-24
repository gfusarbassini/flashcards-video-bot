import pandas as pd
import sys
import os
import io
import requests
import cairosvg
from google import genai
from gtts import gTTS
from pydub import AudioSegment
from moviepy.editor import ImageClip, concatenate_videoclips
from ftplib import FTP
from concurrent.futures import ThreadPoolExecutor
import time
import numpy as np
from PIL import Image

# --- CONFIG ---
CSV_FILE = "parole.csv"
BASI_DIR = "flashcards/BASI"
ASSET_DIR = "flashcards/ASSET"
os.makedirs(ASSET_DIR, exist_ok=True)

FTP_HOST = "ftp.roadtominds.altervista.org"
FTP_USER = "roadtominds"
FTP_PASS = os.getenv("FTP_PASSWORD")
FTP_DIR = "Flashcards"

# --- GEMINI CLIENT PERSISTENTE ---
GEMINI_CLIENT = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# --- PROFILING ---
def timeit(func):
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        print(f"⏱️  {func.__name__}: {time.time()-start:.2f}s")
        return result
    return wrapper

# --- TEXT WRAP SVG ---
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

    if line:
        lines.append(" ".join(line))

    tspans = []
    for i, l in enumerate(lines):
        dy = "0em" if i == 0 else "1.2em"
        tspans.append(f'<tspan x="118.18359" dy="{dy}">{l}</tspan>')

    return "".join(tspans)

# --- SVG → NUMPY ---
def svg_to_array(svg_content):
    png_data = cairosvg.svg2png(bytestring=svg_content.encode("utf-8"))
    img = Image.open(io.BytesIO(png_data))
    return np.array(img)

# --- VIDEO ---
@timeit
def crea_video_ultra_fast(parola, trad, nota_es_wrapped, base_file, out_video):
    with open(base_file, "r", encoding="utf-8") as f:
        svg_template = f.read()

    frame_configs = [
        ("", trad, "", 1),
        ("", trad, "5", 1),
        ("", trad, "4", 1),
        ("", trad, "3", 1),
        ("", trad, "2", 1),
        ("", trad, "1", 1),
        (parola, trad, nota_es_wrapped, 5),
    ]

    clips = []
    for p, t, n, dur in frame_configs:
        svg = svg_template.replace("PAROLAPAROLAPAROLA", p)
        svg = svg.replace("TRADUZIONETRADUZIONETRADUZIONE", t)
        svg = svg.replace("NOTAESEMPIO", n)
        arr = svg_to_array(svg)
        clips.append(ImageClip(arr).set_duration(dur))

    video = concatenate_videoclips(clips, method="compose")

    video.write_videofile(
        out_video,
        fps=12,                     # 🔥 meno frame
        codec="libx264",
        audio=False,
        preset="ultrafast",         # 🔥 encoding più veloce
        threads=4,
        logger=None
    )

# --- TELEGRAM ---
@timeit
def send_telegram(chat_id, text, voice_path, token):
    with requests.Session() as session:
        base_url = f"https://api.telegram.org/bot{token}"

        session.post(
            f"{base_url}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10
        )

        with open(voice_path, "rb") as v:
            session.post(
                f"{base_url}/sendVoice",
                data={"chat_id": chat_id},
                files={"voice": v},
                timeout=10
            )

# --- AUDIO ---
@timeit
def genera_audio(parola_russa, output_ogg):
    tts = gTTS(text=f"{parola_russa}... {parola_russa}... {parola_russa}", lang="ru")
    mp3_buffer = io.BytesIO()
    tts.write_to_fp(mp3_buffer)
    mp3_buffer.seek(0)

    audio = AudioSegment.from_file(mp3_buffer, format="mp3")
    rallentato = audio._spawn(
        audio.raw_data,
        overrides={"frame_rate": int(audio.frame_rate * 0.75)},
    )
    rallentato.set_frame_rate(audio.frame_rate).export(
        output_ogg, format="ogg", codec="libopus"
    )

# --- GEMINI CSV ---
@timeit
def generate_csv_record(input_word):
    prompt = (
        f"Analizza '{input_word}'. "
        "Se è italiano traduci in russo, altrimenti mantieni. "
        "Rispondi con UNA SOLA riga CSV (6 campi separati da ','): "
        "Parola(RU), Traduzione(IT), Spiegazione(RU A1+), Nota, Esempio(RU-IT), Video(vuoto)."
    )

    try:
        response = GEMINI_CLIENT.models.generate_content(
            model="gemini-3-flash-preview",
            contents=prompt,
        )
        
        # Check if response and text exist
        if not response or not response.text:
            print(f"⚠️ Gemini returned an empty response for: {input_word}")
            return None

        clean_text = (
            response.text.strip()
            .replace("```csv", "")
            .replace("```", "")
            .split("\n")[0]
        )
        return clean_text

    except Exception as e:
        print(f"❌ Error during Gemini generation: {e}")
        return None
# --- FTP ---
@timeit
def upload_to_ftp(local_path, remote_filename):
    try:
        ftp = FTP()
        ftp.encoding = "latin-1"
        ftp.connect(FTP_HOST, timeout=30)
        ftp.login(FTP_USER, FTP_PASS)
        ftp.set_pasv(True)
        ftp.cwd(FTP_DIR)

        with open(local_path, "rb") as f:
            ftp.storbinary(
                f"STOR {remote_filename}",
                f,
                blocksize=32768,   # 🔥 blocchi più grandi
            )

        ftp.quit()
        print(f"✅ Caricato su FTP: {remote_filename}")
        return True

    except Exception as e:
        print(f"❌ Errore FTP: {e}")
        return False

# --- MAIN ---
if __name__ == "__main__":
    total_start = time.time()

    if len(sys.argv) < 2:
        sys.exit(1)

    input_word = sys.argv[1]
    chat_id = sys.argv[2] if len(sys.argv) > 2 else None
    bot_token = os.getenv("TELEGRAM_TOKEN")

    cols = ["Parola", "Traduzione", "Spiegazione", "Nota", "Esempio", "FileVideo"]

    if os.path.exists(CSV_FILE):
        df_old = pd.read_csv(CSV_FILE)
        current_count = len(df_old) + 21
    else:
        df_old = pd.DataFrame(columns=cols)
        current_count = 21

    video_filename = f"{current_count:02d}_video.mp4"

    # CSV
    line = generate_csv_record(input_word)
    new_row = pd.read_csv(
        io.StringIO(line),
        header=None,
        names=cols,
        quotechar='"',
        skipinitialspace=True,
    ).fillna("")

    new_row.at[0, "FileVideo"] = video_filename

    parola_ru = str(new_row["Parola"].iloc[0])
    trad_it = str(new_row["Traduzione"].iloc[0])

    video_local_path = os.path.join(ASSET_DIR, video_filename)
    nota_wrap = wrap_text(f"{new_row['Nota'].iloc[0]} {new_row['Esempio'].iloc[0]}")

    pd.concat([df_old, new_row], ignore_index=True).to_csv(CSV_FILE, index=False)
    print("✅ CSV salvato")

    with ThreadPoolExecutor(max_workers=3) as executor:
        audio_future = executor.submit(genera_audio, parola_ru, "voice.ogg")
        video_future = executor.submit(
            crea_video_ultra_fast,
            parola_ru,
            trad_it,
            nota_wrap,
            os.path.join(BASI_DIR, "base_frame3.svg"),
            video_local_path,
        )

        audio_future.result()

        if chat_id and bot_token:
            msg = (
                f"🇷🇺 *{parola_ru}*\n"
                f"🇮🇹 {trad_it}\n\n"
                f"📖 {new_row['Spiegazione'].iloc[0]}\n"
                f"💬 {new_row['Esempio'].iloc[0]}"
            )
            telegram_future = executor.submit(
                send_telegram, chat_id, msg, "voice.ogg", bot_token
            )

        video_future.result()

        ftp_future = executor.submit(
            upload_to_ftp, video_local_path, video_filename
        )

        if chat_id and bot_token:
            telegram_future.result()

        ftp_future.result()

    print(f"\n🏁 TEMPO TOTALE: {time.time()-total_start:.2f}s")
    print(f"✅ Completato: {video_filename} per {parola_ru}")
