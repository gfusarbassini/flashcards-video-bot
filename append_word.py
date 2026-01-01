# append_word.py

import pandas as pd
import sys
import os
from google import genai
from google.genai import types
import io
import requests
from gtts import gTTS

# --- Funzioni per l'invio a Telegram ---

def send_telegram_text(chat_id, text, token):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Errore invio testo Telegram: {e}")

def send_telegram_audio(chat_id, audio_path, token):
    url = f"https://api.telegram.org/bot{token}/sendAudio"
    try:
        with open(audio_path, 'rb') as audio:
            files = {'audio': audio}
            data = {'chat_id': chat_id}
            requests.post(url, data=data, files=files)
    except Exception as e:
        print(f"Errore invio audio Telegram: {e}")

# --- Funzione per la chiamata API di Gemini ---

def generate_csv_record(input_word):
    """
    Chiama l'API di Gemini per generare i dati del record CSV.
    """
    if 'GEMINI_API_KEY' not in os.environ:
        print("ATTENZIONE: La variabile d'ambiente GEMINI_API_KEY non è impostata.")
        return None
        
    try:
        client = genai.Client()
    except Exception as e:
        raise ConnectionError(f"Errore di inizializzazione del client Gemini: {e}")

    prompt = (
        f"Analizza la parola fornita: '{input_word}'. "
        "Se la parola è in italiano, traducila in russo. Se è già in russo, mantienila così. "
        "Genera i campi per un record CSV con questa struttura rigorosa:\n"
        "1. Parola (sempre e solo in cirillico)\n"
        "2. Traduzione (sempre e solo in italiano)\n"
        "3. Spiegazione (A1 russo, semplice)\n"
        "4. Nota (genere, particolarità o contesto)\n"
        "5. Esempio (frase in russo con traduzione italiana)\n"
        "6. FileVideo (lascia vuoto, ovvero metti solo la virgola finale)\n\n"
        "REGOLE DI OUTPUT:\n"
        "- Rispondi SOLO con la riga CSV.\n"
        "- Usa la virgola come separatore.\n"
        "- Usa le virgolette doppie per i campi che contengono virgole.\n"
        "Esempio:\n"
        "яблоко,mela,\"Frutto rotondo e dolce.\",Neutro.,\"Я ем яблоко. — Mangio una mela.\","
    )

    try:
        print(f"Chiamata a Gemini per elaborare '{input_word}'...")
        response = client.models.generate_content(
            model='gemini-3-flash-preview', # Usando il modello aggiornato
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1
            )
        )
        record_line = response.text.strip()
        # Rimuove eventuali backticks se Gemini risponde in formato markdown code
        record_line = record_line.replace('```csv', '').replace('```', '').strip()
        return record_line

    except Exception as e:
        print(f"Errore nella chiamata API di Gemini per '{input_word}': {e}")
        return None

# --- Inizio dello Script Principale ---

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Errore: Inserisci una parola come argomento.")
        sys.exit(1)

    input_word = sys.argv[1]
    # Recuperiamo il chat_id se passato, altrimenti None
    chat_id = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] != "" else None
    bot_token = os.getenv("TELEGRAM_TOKEN")
    
    csv_file = 'parole.csv'
    column_names = ['Parola', 'Traduzione', 'Spiegazione (A1 russo)', 'Nota', 'Esempio', 'FileVideo']

    # 1. Genera il Record tramite Gemini
    csv_record_line = generate_csv_record(input_word)

    if not csv_record_line:
        print("Fallimento: Impossibile generare il record. Uscita.")
        sys.exit(1)

    print(f"Dati ricevuti: {csv_record_line}")

    # 2. Parsing della riga ricevuta
    try:
        new_row_df = pd.read_csv(io.StringIO(csv_record_line), 
                                 header=None, 
                                 names=column_names, 
                                 quotechar='"', 
                                 skipinitialspace=True)
    except Exception as e:
        print(f"Errore di parsing CSV: {e}")
        sys.exit(1)

    # 3. Generazione Audio (3 volte la parola russa)
    parola_russa = new_row_df['Parola'].iloc[0]
    testo_audio = f"{parola_russa}... {parola_russa}... {parola_russa}"
    audio_file = "pronuncia.mp3"
    
    try:
        tts = gTTS(text=testo_audio, lang='ru')
        tts.save(audio_file)
    except Exception as e:
        print(f"Errore generazione audio: {e}")
        audio_file = None

    # 4. Invio a Telegram (se abbiamo il chat_id)
    if chat_id and bot_token:
        traduzione = new_row_df['Traduzione'].iloc[0]
        spiegazione = new_row_df['Spiegazione (A1 russo)'].iloc[0]
        esempio = new_row_df['Esempio'].iloc[0]
        
        messaggio = (
            f"🇷🇺 *{parola_russa}*\n"
            f"🇮🇹 {traduzione}\n\n"
            f"📖 {spiegazione}\n"
            f"💬 {esempio}"
        )
        
        send_telegram_text(chat_id, messaggio, bot_token)
        if audio_file:
            send_telegram_audio(chat_id, audio_file, bot_token)

    # 5. Carica/Crea CSV e Salva
    try:
        df = pd.read_csv(csv_file)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        df = pd.DataFrame(columns=column_names)

    df = pd.concat([df, new_row_df], ignore_index=True)
    df.to_csv(csv_file, index=False)

    print(f"✅ Successo! Aggiunta la parola '{parola_russa}' a {csv_file}.")
