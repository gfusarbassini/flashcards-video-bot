import pandas as pd
import sys
import os
from google import genai
from google.genai import types
import io
import requests
from gtts import gTTS
from pydub import AudioSegment  # Per manipolare la velocità

# --- Funzioni per l'invio a Telegram ---

def send_telegram_text(chat_id, text, token):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Errore invio testo: {e}")

def send_telegram_voice(chat_id, audio_path, token):
    # Usiamo sendVoice per inviarlo come nota vocale
    url = f"https://api.telegram.org/bot{token}/sendVoice"
    try:
        with open(audio_path, 'rb') as voice:
            files = {'voice': voice}
            data = {'chat_id': chat_id}
            requests.post(url, data=data, files=files)
    except Exception as e:
        print(f"Errore invio nota vocale: {e}")

# --- Funzione per rallentare l'audio ---

def scale_speed(input_file, output_file, speed=0.8):
    """ Rallenta l'audio senza cambiare il tono (pitch) """
    audio = AudioSegment.from_file(input_file)
    # Manipolazione del frame rate per cambiare la velocità
    new_sample_rate = int(audio.frame_rate * speed)
    rallentato = audio._spawn(audio.raw_data, overrides={'frame_rate': new_sample_rate})
    rallentato = rallentato.set_frame_rate(audio.frame_rate)
    rallentato.export(output_file, format="ogg", codec="libopus") # Formato nativo note vocali

# --- Funzione Gemini (Tua originale con piccola pulizia) ---

def generate_csv_record(input_word):
    if 'GEMINI_API_KEY' not in os.environ: return None
    client = genai.Client()
    prompt = (
        f"Analizza: '{input_word}'. Traduci in russo (se it) o mantieni (se ru). "
        "Rispondi SOLO con una riga CSV: Parola(cirillico),Traduzione(it),Spiegazione(A1),Nota,Esempio, "
    )
    try:
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.1)
        )
        return response.text.strip().replace('```csv', '').replace('```', '').strip()
    except: return None

# --- Main ---

if __name__ == "__main__":
    if len(sys.argv) < 2: sys.exit(1)

    input_word = sys.argv[1]
    chat_id = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] != "" else None
    bot_token = os.getenv("TELEGRAM_TOKEN")
    
    csv_file = 'parole.csv'
    column_names = ['Parola', 'Traduzione', 'Spiegazione', 'Nota', 'Esempio', 'FileVideo']

    csv_line = generate_csv_record(input_word)
    if not csv_line: sys.exit(1)

    try:
        new_row_df = pd.read_csv(io.StringIO(csv_line), header=None, names=column_names, quotechar='"', skipinitialspace=True)
    except: sys.exit(1)

    # --- Gestione Audio ---
    parola_russa = new_row_df['Parola'].iloc[0]
    temp_file = "temp.mp3"
    final_voice = "voice.ogg"
    
    # Genera audio normale (3 volte)
    testo_audio = f"{parola_russa}... {parola_russa}... {parola_russa}"
    tts = gTTS(text=testo_audio, lang='ru')
    tts.save(temp_file)

    # Rallenta l'audio (0.8 è il 20% più lento, prova 0.7 se vuoi ancora più lento)
    scale_speed(temp_file, final_voice, speed=0.8)

    # --- Invio ---
    if chat_id and bot_token:
        msg = f"🇷🇺 *{parola_russa}*\n🇮🇹 {new_row_df['Traduzione'].iloc[0]}\n\n📖 {new_row_df['Spiegazione'].iloc[0]}\n💬 {new_row_df['Esempio'].iloc[0]}"
        send_telegram_text(chat_id, msg, bot_token)
        send_telegram_voice(chat_id, final_voice, bot_token)

    # --- Salvataggio CSV ---
    try:
        df = pd.read_csv(csv_file)
    except:
        df = pd.DataFrame(columns=column_names)
    
    df = pd.concat([df, new_row_df], ignore_index=True)
    df.to_csv(csv_file, index=False)
    print(f"✅ Completato per {parola_russa}")
