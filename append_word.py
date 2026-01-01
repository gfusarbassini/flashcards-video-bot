import pandas as pd
import sys
import os
from google import genai
from google.genai import types
import io
import requests
from gtts import gTTS
from pydub import AudioSegment

# --- Funzioni Telegram ---
def send_telegram_text(chat_id, text, token):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

def send_telegram_voice(chat_id, audio_path, token):
    url = f"https://api.telegram.org/bot{token}/sendVoice"
    with open(audio_path, 'rb') as voice:
        requests.post(url, data={'chat_id': chat_id}, files={'voice': voice})

# --- Funzione Audio ---
def scale_speed(input_file, output_file, speed=0.75):
    try:
        audio = AudioSegment.from_file(input_file)
        new_sample_rate = int(audio.frame_rate * speed)
        rallentato = audio._spawn(audio.raw_data, overrides={'frame_rate': new_sample_rate})
        rallentato = rallentato.set_frame_rate(audio.frame_rate)
        # Esportiamo in OGG per Telegram nota vocale
        rallentato.export(output_file, format="ogg", codec="libopus")
        return True
    except Exception as e:
        print(f"ERRORE AUDIO: {e}")
        return False

# --- Funzione Gemini ---
def generate_csv_record(input_word):
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        print("ERRORE: Chiave API mancante.")
        return None
    
    client = genai.Client(api_key=api_key)
    prompt = (
        f"Analizza: '{input_word}'. Traduci in russo (se it) o mantieni (se ru). "
        "Rispondi SOLO con una riga CSV rigorosa con 6 campi separati da virgola: "
        "Parola(cirillico),Traduzione(it),Spiegazione(A1),Nota,Esempio,VideoVuoto. "
        "Usa virgolette doppie se ci sono virgole interne."
    )
    
    try:
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.1)
        )
        # Pulizia stringa da possibili Markdown o spazi bianchi
        line = response.text.strip().replace('```csv', '').replace('```', '').split('\n')[0]
        return line
    except Exception as e:
        print(f"ERRORE GEMINI: {e}")
        return None

# --- Main ---
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("ERRORE: Argomenti mancanti.")
        sys.exit(1)

    input_word = sys.argv[1]
    chat_id = sys.argv[2] if len(sys.argv) > 2 else None
    bot_token = os.getenv("TELEGRAM_TOKEN")
    
    csv_file = 'parole.csv'
    column_names = ['Parola', 'Traduzione', 'Spiegazione', 'Nota', 'Esempio', 'FileVideo']

    # 1. Ottieni dati da Gemini
    csv_line = generate_csv_record(input_word)
    if not csv_line:
        sys.exit(1)
    print(f"Riga generata: {csv_line}")

    # 2. Parsing CSV
    try:
        new_row_df = pd.read_csv(io.StringIO(csv_line), header=None, names=column_names, quotechar='"', skipinitialspace=True).fillna('')
    except Exception as e:
        print(f"ERRORE PARSING CSV: {e}")
        sys.exit(1)

    parola_russa = str(new_row_df['Parola'].iloc[0])

    # 3. Gestione Audio
    temp_mp3 = "temp.mp3"
    final_voice = "voice.ogg"
    
    try:
        tts = gTTS(text=f"{parola_russa}... {parola_russa}... {parola_russa}", lang='ru')
        tts.save(temp_mp3)
        audio_ok = scale_speed(temp_mp3, final_voice, speed=0.75)
    except Exception as e:
        print(f"ERRORE TTS: {e}")
        audio_ok = False

    # 4. Telegram
    if chat_id and bot_token:
        try:
            msg = f"🇷🇺 *{parola_russa}*\n🇮🇹 {new_row_df['Traduzione'].iloc[0]}\n\n📖 {new_row_df['Spiegazione'].iloc[0]}\n💬 {new_row_df['Esempio'].iloc[0]}"
            send_telegram_text(chat_id, msg, bot_token)
            if audio_ok:
                send_telegram_voice(chat_id, final_voice, bot_token)
        except Exception as e:
            print(f"ERRORE INVIO TELEGRAM: {e}")

    # 5. Salvataggio locale
    try:
        if os.path.exists(csv_file):
            df = pd.read_csv(csv_file)
            df = pd.concat([df, new_row_df], ignore_index=True)
        else:
            df = new_row_df
        df.to_csv(csv_file, index=False)
        print(f"✅ Completato per {parola_russa}")
    except Exception as e:
        print(f"ERRORE SALVATAGGIO CSV: {e}")
        sys.exit(1)
