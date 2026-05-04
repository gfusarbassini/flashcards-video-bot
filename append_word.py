import pandas as pd
import sys
import os
import io
import requests
import cairosvg
import time
import signal
import numpy as np
from google import genai
from gtts import gTTS
from pydub import AudioSegment
from moviepy.editor import ImageClip, concatenate_videoclips
from ftplib import FTP
from concurrent.futures import ThreadPoolExecutor
from PIL import Image

# Configurazione directory e parametri FTP
CSV_FILE = "parole.csv"
BASI_DIR = "flashcards/BASI"
ASSET_DIR = "flashcards/ASSET"
os.makedirs(ASSET_DIR, exist_ok=True)

FTP_HOST = "ftp.roadtominds.altervista.org"
FTP_USER = "roadtominds"
FTP_PASS = os.getenv("FTP_PASSWORD")
FTP_DIR = "Flashcards"

# Instagram
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")  # Page token per i Reels
IG_USER_ID = "17841444282984648"
FB_PAGE_ID = "741836139020105"
API_VERSION = "v21.0"
GRAPH_URL = f"https://graph.facebook.com/{API_VERSION}"
VIDEO_BASE_URL = "https://roadtominds.altervista.org/Flashcards/"

GEMINI_CLIENT = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# --- TIMEOUT HANDLER ---

TIMEOUT_SECONDS = 180  # 3 minuti

def timeout_handler(signum, frame):
    raise TimeoutError("Timeout superato")


# --- TELEGRAM ---

def send_telegram_text(chat_id, text, token):
    base_url = f"https://api.telegram.org/bot{token}"
    requests.post(f"{base_url}/sendMessage", json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})


def send_telegram(chat_id, text, voice_path, token):
    """Invia il riepilogo testuale e il file vocale al bot Telegram."""
    base_url = f"https://api.telegram.org/bot{token}"
    requests.post(f"{base_url}/sendMessage", json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})
    with open(voice_path, "rb") as v:
        requests.post(f"{base_url}/sendVoice", data={"chat_id": chat_id}, files={"voice": v})


def kill_github_action(token):
    """Termina il processo corrente (GitHub Action) con SIGTERM."""
    send_telegram_text(
        os.getenv("TELEGRAM_CHAT_ID_ADMIN"),
        "⚠️ Generazione flashcard: timeout dopo 3 minuti. Action killata.",
        token
    )
    os.kill(os.getpid(), signal.SIGTERM)


# --- TEXT UTILS ---

def wrap_text(text, width=36):
    """Formatta il testo per l'inserimento negli elementi tspan dell'SVG."""
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


# --- SVG / VIDEO ---

def svg_to_array(svg_content):
    """Converte SVG in array numpy passando per PNG in memoria."""
    png_data = cairosvg.svg2png(bytestring=svg_content.encode("utf-8"))
    img = Image.open(io.BytesIO(png_data))
    return np.array(img)


def crea_video_ultra_fast(parola, trad, nota_es_wrapped, base_file, out_video):
    """Genera video MP4 assemblando frame statici derivati da template SVG."""
    with open(base_file, "r", encoding="utf-8") as f:
        svg_template = f.read()

    frame_configs = [("", trad, "", 1), ("", trad, "5", 1), ("", trad, "4", 1),
                     ("", trad, "3", 1), ("", trad, "2", 1), ("", trad, "1", 1),
                     (parola, trad, nota_es_wrapped, 5)]

    clips = []
    for p, t, n, dur in frame_configs:
        svg = svg_template.replace("PAROLAPAROLAPAROLA", p).replace("TRADUZIONETRADUZIONETRADUZIONE", t).replace("NOTAESEMPIO", n)
        clips.append(ImageClip(svg_to_array(svg)).set_duration(dur))

    video = concatenate_videoclips(clips, method="compose")
    video.write_videofile(
        out_video,
        fps=30,
        codec="libx264",
        audio=False,
        preset="ultrafast",
        threads=4,
        logger=None
    )


# --- AUDIO ---

def genera_audio(parola_russa, output_ogg):
    """
    Genera audio sintetico, rallenta SENZA cambiare il pitch (time-stretch),
    ed esporta in OGG Opus.
    """
    tts = gTTS(text=f"{parola_russa}... {parola_russa}... {parola_russa}", lang="ru")
    mp3_buffer = io.BytesIO()
    tts.write_to_fp(mp3_buffer)
    mp3_buffer.seek(0)

    audio = AudioSegment.from_file(mp3_buffer, format="mp3")

    try:
        import subprocess
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_in:
            tmp_in.write(mp3_buffer.getvalue())
            tmp_in_path = tmp_in.name

        tmp_out_path = tmp_in_path.replace(".mp3", "_slow.mp3")

        result = subprocess.run([
            "ffmpeg", "-y", "-i", tmp_in_path,
            "-filter:a", "atempo=0.75",
            tmp_out_path
        ], capture_output=True)

        if result.returncode == 0:
            rallentato = AudioSegment.from_file(tmp_out_path, format="mp3")
        else:
            raise RuntimeError("ffmpeg atempo failed")

        os.unlink(tmp_in_path)
        os.unlink(tmp_out_path)

    except Exception:
        original_rate = audio.frame_rate
        slowed = audio._spawn(audio.raw_data, overrides={"frame_rate": int(original_rate * 0.75)})
        rallentato = slowed.set_frame_rate(original_rate)

    rallentato.export(output_ogg, format="ogg", codec="libopus")


# --- FTP ---

def upload_to_ftp(local_path, remote_filename):
    """Gestione upload FTP con codifica latin-1 per compatibilità server."""
    try:
        ftp = FTP()
        ftp.encoding = "latin-1"
        ftp.connect(FTP_HOST, timeout=30)
        ftp.login(FTP_USER, FTP_PASS)
        ftp.set_pasv(True)
        ftp.cwd(FTP_DIR)
        with open(local_path, "rb") as f:
            ftp.storbinary(f"STOR {remote_filename}", f, blocksize=32768)
        ftp.quit()
        return True
    except Exception as e:
        print(f"Errore FTP: {e}")
        return False


# --- INSTAGRAM REEL ---

def publish_reel(video_filename, caption):
    """
    Pubblica il video come Reel su Instagram.
    Usa l'IG_USER_ID con un User Access Token valido e autorizzato per quell'account.
    """
    video_url = f"{VIDEO_BASE_URL}{video_filename}"
    print(f"📤 Pubblicazione Reel: {video_url}")

    # Usa ACCESS_TOKEN (User Token) invece di PAGE_ACCESS_TOKEN se l'ID non viene trovato
    token_to_use = ACCESS_TOKEN 

    try:
        # Step 1: Crea container multimediale
        create_resp = requests.post(
            f"{GRAPH_URL}/{IG_USER_ID}/media",
            data={
                "media_type": "REELS",
                "video_url": video_url,
                "caption": caption,
                "access_token": token_to_use
            }
        )
        
        if not create_resp.ok:
            print(f"❌ Errore creazione container ({create_resp.status_code}): {create_resp.text}")
            # Se fallisce ancora, prova a stampare i dettagli dell'account per debug
            return False

        creation_id = create_resp.json().get("id")
        
        # Step 2: Polling stato
        for _ in range(20):
            time.sleep(5)
            status_resp = requests.get(
                f"{GRAPH_URL}/{creation_id}",
                params={"fields": "status_code,status", "access_token": token_to_use}
            )
            res = status_resp.json()
            if res.get("status_code") == "FINISHED":
                print("✅ Container pronto.")
                break
            if res.get("status_code") in ("ERROR", "EXPIRED"):
                print(f"❌ Errore processing: {res}")
                return False
        else:
            return False

        # Step 3: Pubblicazione finale
        publish_resp = requests.post(
            f"{GRAPH_URL}/{IG_USER_ID}/media_publish",
            data={"creation_id": creation_id, "access_token": token_to_use}
        )
        print(f"✅ Reel pubblicato: {publish_resp.json()}")
        return True

    except Exception as e:
        print(f"❌ Errore: {e}")
        return False



# --- GEMINI ---

def generate_csv_record(input_word, chat_id, bot_token):
    """
    Ottiene dati da Gemini. Se il modello è 503 (overloaded),
    notifica l'utente in russo e attende 3 minuti prima di riprovare.
    """
    prompt = (
        f"Analizza '{input_word}'. Se è italiano traduci in russo, altrimenti mantieni. "
        "Rispondi con UNA SOLA riga CSV (6 campi separati da ','): "
        "Parola(RU), Traduzione(IT), Spiegazione(RU A1+), Nota, Esempio(RU-IT), Video(vuoto)."
    )

    while True:
        try:
            response = GEMINI_CLIENT.models.generate_content(
                model="gemini-3-flash-preview",
                contents=prompt,
            )
            if response and response.text:
                return response.text.strip().replace("```csv", "").replace("```", "").split("\n")[0]
        except Exception as e:
            if "503" in str(e) or "overloaded" in str(e).lower():
                msg_error = "Извините, сервер перегружен. Я попробую еще раз через 3 минуты."
                if chat_id and bot_token:
                    requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage",
                                  json={"chat_id": chat_id, "text": msg_error})
                time.sleep(180)
                continue
            print(f"Errore Gemini critico: {e}")
            return None


# --- MAIN ---

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(1)

    input_word = sys.argv[1]
    chat_id = sys.argv[2] if len(sys.argv) > 2 else None
    bot_token = os.getenv("TELEGRAM_TOKEN")

    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(TIMEOUT_SECONDS)

    try:
        cols = ["Parola", "Traduzione", "Spiegazione", "Nota", "Esempio", "FileVideo"]
        if os.path.exists(CSV_FILE):
            df_old = pd.read_csv(CSV_FILE)
            current_count = len(df_old) + 21
        else:
            df_old = pd.DataFrame(columns=cols)
            current_count = 21

        video_filename = f"{current_count:02d}_video.mp4"
        line = generate_csv_record(input_word, chat_id, bot_token)

        if not line:
            if chat_id and bot_token:
                send_telegram_text(chat_id, "❌ Errore nella generazione della flashcard.", bot_token)
            sys.exit(1)

        new_row = pd.read_csv(io.StringIO(line), header=None, names=cols, quotechar='"', skipinitialspace=True).fillna("")
        new_row.at[0, "FileVideo"] = video_filename

        parola_ru = str(new_row["Parola"].iloc[0])
        trad_it = str(new_row["Traduzione"].iloc[0])
        spiegazione = str(new_row["Spiegazione"].iloc[0])
        esempio = str(new_row["Esempio"].iloc[0])
        video_local_path = os.path.join(ASSET_DIR, video_filename)
        nota_wrap = wrap_text(f"{new_row['Nota'].iloc[0]} {new_row['Esempio'].iloc[0]}")

        # 1) Prima invia la risposta su Telegram
        if chat_id and bot_token:
            msg = f"🇷🇺 *{parola_ru}*\n🇮🇹 {trad_it}\n\n📖 {spiegazione}\n💬 {esempio}"
            genera_audio(parola_ru, "voice.ogg")
            send_telegram(chat_id, msg, "voice.ogg", bot_token)

        # Aggiorna il CSV
        pd.concat([df_old, new_row], ignore_index=True).to_csv(CSV_FILE, index=False)

        # Genera il video
        crea_video_ultra_fast(
            parola_ru, trad_it, nota_wrap,
            os.path.join(BASI_DIR, "base_frame3.svg"),
            video_local_path
        )

        # Upload FTP
        upload_to_ftp(video_local_path, video_filename)

        # Pubblica come Reel su Instagram
        caption = f"🇷🇺 {parola_ru} = 🇮🇹 {trad_it}\n\n{spiegazione}\n\n#russo #flashcard #imparare"
        publish_reel(video_filename, caption)

        signal.alarm(0)

    except TimeoutError:
        if chat_id and bot_token:
            send_telegram_text(
                chat_id,
                "⚠️ Generazione flashcard in timeout dopo 3 minuti. Operazione annullata.",
                bot_token
            )
        kill_github_action(bot_token)
        sys.exit(1)
