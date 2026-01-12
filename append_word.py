import pandas as pd
import sys
import os
import io
import requests
import tempfile
import cairosvg
from google import genai
from gtts import gTTS
from pydub import AudioSegment
from moviepy.editor import ImageClip, concatenate_videoclips
from ftplib import FTP
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
import multiprocessing as mp

# --- CONFIGURAZIONE ---
CSV_FILE = "parole.csv"
BASI_DIR = "flashcards/BASI"
ASSET_DIR = "flashcards/ASSET"
os.makedirs(ASSET_DIR, exist_ok=True)

FTP_HOST = "ftp.roadtominds.altervista.org"
FTP_USER = "roadtominds"
FTP_PASS = os.getenv("FTP_PASSWORD")
FTP_DIR = "Flashcards"

@lru_cache(maxsize=1)
def load_svg_template():
    """Cache SVG template - carica una sola volta"""
    with open(os.path.join(BASI_DIR, "base_frame3.svg"), "r", encoding="utf-8") as f:
        return f.read()

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

def generate_frame_png(args):
    """Genera un singolo frame PNG (parallelizzabile)"""
    svg_content, idx = args
    tmp_path = f"frame_{idx}.png"
    cairosvg.svg2png(bytestring=svg_content.encode("utf-8"), write_to=tmp_path)
    return tmp_path, idx

def crea_video(parola, trad, nota_es_wrapped, out_video):
    """Versione parallelizzata della generazione video"""
    svg_template = load_svg_template()
    
    # Prepara tutti i frame SVG (operazione veloce)
    frames_data = []
    frames_data.append((svg_template.replace("PAROLAPAROLAPAROLA", "")
                                    .replace("TRADUZIONETRADUZIONETRADUZIONE", trad)
                                    .replace("NOTAESEMPIO", ""), 0))
    
    for i, num in enumerate(range(5, 0, -1), 1):
        frames_data.append((svg_template.replace("PAROLAPAROLAPAROLA", "")
                                        .replace("TRADUZIONETRADUZIONETRADUZIONE", trad)
                                        .replace("NOTAESEMPIO", str(num)), i))
    
    frames_data.append((svg_template.replace("PAROLAPAROLAPAROLA", parola)
                                    .replace("TRADUZIONETRADUZIONETRADUZIONE", trad)
                                    .replace("NOTAESEMPIO", nota_es_wrapped), 6))
    
    # PARALLELIZZA la conversione SVG→PNG (bottleneck principale)
    frame_paths = [None] * 7
    with ThreadPoolExecutor(max_workers=min(7, mp.cpu_count())) as executor:
        futures = {executor.submit(generate_frame_png, frame): frame for frame in frames_data}
        for future in as_completed(futures):
            path, idx = future.result()
            frame_paths[idx] = path
    
    # Crea clips con durate appropriate
    clips = []
    durations = [1, 1, 1, 1, 1, 1, 5]
    for path, duration in zip(frame_paths, durations):
        clips.append(ImageClip(path).set_duration(duration))
    
    video = concatenate_videoclips(clips, method="compose")
    video.write_videofile(out_video, fps=24, codec="libx264", audio=False, logger=None, 
                         threads=mp.cpu_count())  # Usa tutti i core per encoding
    
    # Cleanup
    for path in frame_paths:
        if os.path.exists(path):
            os.remove(path)

def send_telegram(chat_id, text, voice_path, token):
    """Versione con session reusable (più veloce)"""
    with requests.Session() as session:
        base_url = f"https://api.telegram.org/bot{token}"
        session.post(f"{base_url}/sendMessage", 
                    json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})
        with open(voice_path, 'rb') as v:
            session.post(f"{base_url}/sendVoice", 
                        data={'chat_id': chat_id}, files={'voice': v})

def genera_audio(parola_russa, output_ogg):
    """Ottimizzato: usa BytesIO invece di file temporaneo"""
    tts = gTTS(text=f"{parola_russa}... {parola_russa}... {parola_russa}", lang='ru')
    
    # Usa BytesIO invece di scrivere su disco
    mp3_buffer = io.BytesIO()
    tts.write_to_fp(mp3_buffer)
    mp3_buffer.seek(0)
    
    audio = AudioSegment.from_file(mp3_buffer, format="mp3")
    rallentato = audio._spawn(audio.raw_data, 
                             overrides={'frame_rate': int(audio.frame_rate * 0.75)})
    rallentato.set_frame_rate(audio.frame_rate).export(output_ogg, format="ogg", codec="libopus")

def generate_csv_record(input_word):
    client = genai.Client(api_key=os.getenv('GEMINI_API_KEY'))
    prompt = (
        f"Analizza: '{input_word}'. Se è in italiano traduci in russo, altrimenti mantieni. "
        "Rispondi SOLO con una riga CSV rigorosa (6 campi); i campi devono essere nella maniera più assoluta separati da ',' e non da ';': "
        "1.Parola(RU), 2.Traduzione(IT), 3.Spiegazione(SOLO IN RUSSO SEMPLICE LIVELLO A1+), 4.Nota, 5.Esempio(RU-IT), 6.Video(lascia vuoto)."
    )
    response = client.models.generate_content(model='gemini-3-flash-preview', contents=prompt)
    return response.text.strip().replace('```csv', '').replace('```', '').split('\n')[0]

def upload_to_ftp(local_path, remote_filename):
    """FTP upload separato per parallelizzazione"""
    try:
        ftp = FTP()
        ftp.encoding = "latin-1"
        ftp.connect(FTP_HOST)
        ftp.login(FTP_USER, FTP_PASS)
        ftp.set_pasv(True)
        ftp.cwd(FTP_DIR)
        
        with open(local_path, "rb") as f:
            ftp.storbinary(f"STOR {remote_filename}", f)
        
        ftp.quit()
        print(f"✅ Caricato su FTP: {remote_filename}")
        return True
    except Exception as e:
        print(f"❌ Errore FTP: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) < 2: 
        sys.exit(1)
    
    input_word = sys.argv[1]
    chat_id = sys.argv[2] if len(sys.argv) > 2 else None
    bot_token = os.getenv("TELEGRAM_TOKEN")

    # 1. Caricamento CSV (ottimizzato con usecols se necessario)
    cols = ['Parola', 'Traduzione', 'Spiegazione', 'Nota', 'Esempio', 'FileVideo']
    if os.path.exists(CSV_FILE):
        df_old = pd.read_csv(CSV_FILE)
        current_count = len(df_old) + 21
    else:
        df_old = pd.DataFrame(columns=cols)
        current_count = 21

    video_filename = f"{current_count:02d}_video.mp4"

    # 2. Gemini API call
    line = generate_csv_record(input_word)
    new_row = pd.read_csv(io.StringIO(line), header=None, names=cols, 
                         quotechar='"', skipinitialspace=True).fillna('')
    new_row.at[0, 'FileVideo'] = video_filename
    
    parola_ru = str(new_row['Parola'].iloc[0])
    trad_it = str(new_row['Traduzione'].iloc[0])

    # 3. PARALLELIZZA: Audio + Video generation
    video_local_path = os.path.join(ASSET_DIR, video_filename)
    nota_wrap = wrap_text(f"{new_row['Nota'].iloc[0]} {new_row['Esempio'].iloc[0]}")
    
    with ThreadPoolExecutor(max_workers=2) as executor:
        # Audio e Video in parallelo (operazioni indipendenti)
        audio_future = executor.submit(genera_audio, parola_ru, "voice.ogg")
        video_future = executor.submit(crea_video, parola_ru, trad_it, nota_wrap, video_local_path)
        
        # Attendi completamento
        audio_future.result()
        video_future.result()
    
    # 4. Telegram (dopo audio)
    if chat_id and bot_token:
        msg = f"🇷🇺 *{parola_ru}*\n🇮🇹 {trad_it}\n\n📖 {new_row['Spiegazione'].iloc[0]}\n💬 {new_row['Esempio'].iloc[0]}"
        send_telegram(chat_id, msg, "voice.ogg", bot_token)

    # 5. FTP upload in background (non blocca il salvataggio CSV)
    with ThreadPoolExecutor(max_workers=1) as executor:
        ftp_future = executor.submit(upload_to_ftp, video_local_path, video_filename)
    
    # 6. Salva CSV immediatamente (non aspettare FTP)
    pd.concat([df_old, new_row], ignore_index=True).to_csv(CSV_FILE, index=False)
    print(f"✅ CSV salvato: {video_filename} per {parola_ru}")
    
    # Attendi FTP (opzionale, puoi rimuovere se vuoi terminare subito)
    ftp_future.result()
    print(f"✅ Processo completo per {parola_ru}")
