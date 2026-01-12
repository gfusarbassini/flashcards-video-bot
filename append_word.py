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

# --- CONFIGURAZIONE ---
CSV_FILE = "parole.csv"
BASI_DIR = "flashcards/BASI"
ASSET_DIR = "flashcards/ASSET"
os.makedirs(ASSET_DIR, exist_ok=True)

FTP_HOST = "ftp.roadtominds.altervista.org"
FTP_USER = "roadtominds"
FTP_PASS = os.getenv("FTP_PASSWORD")
FTP_DIR = "Flashcards"

# PROFILING DECORATOR
def timeit(func):
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        print(f"⏱️  {func.__name__}: {time.time()-start:.2f}s")
        return result
    return wrapper

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

# Funzione globale per ProcessPoolExecutor
def svg_to_array(svg_content):
    """Converti SVG direttamente in numpy array (più veloce di salvare su disco)"""
    png_data = cairosvg.svg2png(bytestring=svg_content.encode("utf-8"))
    img = Image.open(io.BytesIO(png_data))
    return np.array(img)

@timeit
def crea_video_ultra_fast(parola, trad, nota_es_wrapped, base_file, out_video):
    """VERSIONE ULTRA-OTTIMIZZATA: carica SVG una volta, genera frame in-memory"""
    with open(base_file, "r", encoding="utf-8") as f:
        svg_template = f.read()
    
    # Definisci i 7 frame
    frame_configs = [
        ("", trad, "", 1),
        ("", trad, "5", 1),
        ("", trad, "4", 1),
        ("", trad, "3", 1),
        ("", trad, "2", 1),
        ("", trad, "1", 1),
        (parola, trad, nota_es_wrapped, 5)
    ]
    
    # PARALLELIZZA la generazione degli array numpy
    clips = []
    svgs = []
    for p, t, n, dur in frame_configs:
        svg = svg_template.replace("PAROLAPAROLAPAROLA", p)
        svg = svg.replace("TRADUZIONETRADUZIONETRADUZIONE", t)
        svg = svg.replace("NOTAESEMPIO", n)
        svgs.append((svg, dur))
    
    # Usa ThreadPoolExecutor (più semplice, evita problemi di pickling)
    with ThreadPoolExecutor(max_workers=4) as executor:
        arrays = list(executor.map(svg_to_array, [s[0] for s in svgs]))
    
    for arr, (_, dur) in zip(arrays, svgs):
        clips.append(ImageClip(arr).set_duration(dur))
    
    video = concatenate_videoclips(clips, method="compose")
    video.write_videofile(out_video, fps=24, codec="libx264", audio=False, 
                         logger=None, preset='ultrafast', threads=4)

@timeit
def send_telegram(chat_id, text, voice_path, token):
    with requests.Session() as session:
        base_url = f"https://api.telegram.org/bot{token}"
        session.post(f"{base_url}/sendMessage", 
                    json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
                    timeout=10)
        with open(voice_path, 'rb') as v:
            session.post(f"{base_url}/sendVoice", 
                        data={'chat_id': chat_id}, files={'voice': v},
                        timeout=10)

@timeit
def genera_audio(parola_russa, output_ogg):
    tts = gTTS(text=f"{parola_russa}... {parola_russa}... {parola_russa}", lang='ru')
    mp3_buffer = io.BytesIO()
    tts.write_to_fp(mp3_buffer)
    mp3_buffer.seek(0)
    
    audio = AudioSegment.from_file(mp3_buffer, format="mp3")
    rallentato = audio._spawn(audio.raw_data, 
                             overrides={'frame_rate': int(audio.frame_rate * 0.75)})
    rallentato.set_frame_rate(audio.frame_rate).export(output_ogg, format="ogg", codec="libopus")

@timeit
def generate_csv_record(input_word):
    client = genai.Client(api_key=os.getenv('GEMINI_API_KEY'))
    prompt = (
        f"Analizza: '{input_word}'. Se è in italiano traduci in russo, altrimenti mantieni. "
        "Rispondi SOLO con una riga CSV rigorosa (6 campi); i campi devono essere nella maniera più assoluta separati da ',' e non da ';': "
        "1.Parola(RU), 2.Traduzione(IT), 3.Spiegazione(SOLO IN RUSSO SEMPLICE LIVELLO A1+), 4.Nota, 5.Esempio(RU-IT), 6.Video(lascia vuoto)."
    )
    response = client.models.generate_content(model='gemini-3-flash-preview', contents=prompt)
    return response.text.strip().replace('```csv', '').replace('```', '').split('\n')[0]

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
            ftp.storbinary(f"STOR {remote_filename}", f, blocksize=8192)
        
        ftp.quit()
        print(f"✅ Caricato su FTP: {remote_filename}")
        return True
    except Exception as e:
        print(f"❌ Errore FTP: {e}")
        return False

if __name__ == "__main__":
    total_start = time.time()
    
    if len(sys.argv) < 2: 
        sys.exit(1)
    
    input_word = sys.argv[1]
    chat_id = sys.argv[2] if len(sys.argv) > 2 else None
    bot_token = os.getenv("TELEGRAM_TOKEN")

    # 1. CSV
    cols = ['Parola', 'Traduzione', 'Spiegazione', 'Nota', 'Esempio', 'FileVideo']
    if os.path.exists(CSV_FILE):
        df_old = pd.read_csv(CSV_FILE)
        current_count = len(df_old) + 21
    else:
        df_old = pd.DataFrame(columns=cols)
        current_count = 21

    video_filename = f"{current_count:02d}_video.mp4"

    # 2. Gemini (probabilmente il vero bottleneck)
    line = generate_csv_record(input_word)
    new_row = pd.read_csv(io.StringIO(line), header=None, names=cols, 
                         quotechar='"', skipinitialspace=True).fillna('')
    new_row.at[0, 'FileVideo'] = video_filename
    
    parola_ru = str(new_row['Parola'].iloc[0])
    trad_it = str(new_row['Traduzione'].iloc[0])

    # 3. TUTTO IN PARALLELO (Audio, Video, FTP prep)
    video_local_path = os.path.join(ASSET_DIR, video_filename)
    nota_wrap = wrap_text(f"{new_row['Nota'].iloc[0]} {new_row['Esempio'].iloc[0]}")
    
    # Salva CSV subito (non dipende da nulla)
    pd.concat([df_old, new_row], ignore_index=True).to_csv(CSV_FILE, index=False)
    print(f"✅ CSV salvato")
    
    with ThreadPoolExecutor(max_workers=3) as executor:
        audio_future = executor.submit(genera_audio, parola_ru, "voice.ogg")
        video_future = executor.submit(crea_video_ultra_fast, parola_ru, trad_it, 
                                      nota_wrap, os.path.join(BASI_DIR, "base_frame3.svg"), 
                                      video_local_path)
        
        # Aspetta solo l'audio per Telegram (non bloccare su video)
        audio_future.result()
        
        # 4. Telegram in parallelo con video encoding
        if chat_id and bot_token:
            msg = f"🇷🇺 *{parola_ru}*\n🇮🇹 {trad_it}\n\n📖 {new_row['Spiegazione'].iloc[0]}\n💬 {new_row['Esempio'].iloc[0]}"
            telegram_future = executor.submit(send_telegram, chat_id, msg, "voice.ogg", bot_token)
        
        # Aspetta video prima di FTP
        video_future.result()
        
        # 5. FTP in parallelo con Telegram
        ftp_future = executor.submit(upload_to_ftp, video_local_path, video_filename)
        
        # Aspetta tutto
        if chat_id and bot_token:
            telegram_future.result()
        ftp_future.result()
    
    print(f"\n🏁 TEMPO TOTALE: {time.time()-total_start:.2f}s")
    print(f"✅ Completato: {video_filename} per {parola_ru}")
