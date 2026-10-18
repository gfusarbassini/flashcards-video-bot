#!/usr/bin/env python3
"""
Telegram Russian Quiz Bot (A2+ / B1)
Genera quiz grammaticali e di contesto interrogando Gemini e li invia
come Quiz Poll nativi su Telegram tramite bot API.
"""

import os
import sys
import json
import random
import datetime
import argparse
import requests
import pandas as pd

# Percorsi file
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PAROLE_CSV = os.path.join(BASE_DIR, "parole.csv")
QUIZ_CSV = os.path.join(BASE_DIR, "quiz_database.csv")

QUIZ_COLUMNS = [
    "id",
    "parola",
    "livello",
    "tipo",
    "domanda",
    "opzione_0",
    "opzione_1",
    "opzione_2",
    "opzione_3",
    "corretta_idx",
    "spiegazione",
    "inviato",
    "data_invio",
]


def load_parole():
    """Carica il vocabolario dal CSV."""
    if not os.path.exists(PAROLE_CSV):
        print(f"⚠️ File {PAROLE_CSV} non trovato.")
        return pd.DataFrame(columns=["Parola", "Traduzione", "Nota", "Esempio", "Spiegazione"])
    try:
        df = pd.read_csv(PAROLE_CSV)
        # Rimuove righe con Parola vuota
        df = df.dropna(subset=["Parola"]).drop_duplicates(subset=["Parola"])
        return df
    except Exception as e:
        print(f"❌ Errore nella lettura di {PAROLE_CSV}: {e}")
        return pd.DataFrame()


def load_quiz_database():
    """Carica il database dei quiz o ne inizializza uno nuovo se assente."""
    if os.path.exists(QUIZ_CSV):
        try:
            df = pd.read_csv(QUIZ_CSV, dtype=str)
            df = df.fillna("")
            # Verifica che tutte le colonne siano presenti
            for col in QUIZ_COLUMNS:
                if col not in df.columns:
                    df[col] = ""
            df["inviato"] = pd.to_numeric(df["inviato"], errors="coerce").fillna(0).astype(int)
            return df
        except Exception as e:
            print(f"⚠️ Errore caricamento {QUIZ_CSV}, re-inizializzazione: {e}")
    return pd.DataFrame(columns=QUIZ_COLUMNS)


def save_quiz_database(df):
    """Salva il database aggiornato su CSV."""
    df.to_csv(QUIZ_CSV, index=False)
    print(f"💾 Database salvato in {QUIZ_CSV} ({len(df)} quiz totali).")


def build_gemini_prompt(words_batch):
    """Costruisce il prompt per Gemini chiedendo esercizi di livello A2+/B1."""
    words_desc = []
    for _, row in words_batch.iterrows():
        p = row.get("Parola", "")
        t = row.get("Traduzione", "")
        n = row.get("Nota", "")
        e = row.get("Esempio", "")
        words_desc.append(f"- Parola: {p} | Traduzione: {t} | Nota: {n} | Esempio: {e}")

    words_text = "\n".join(words_desc)

    prompt = f"""Sei un docente esperto di lingua russa per studenti di livello A2+ e B1.
Crea esattamente un quiz a risposta multipla per ciascuna delle seguenti parole:
{words_text}

I quesiti devono essere di livello A2+ / B1 e NON devono essere banali traduzioni.
Alterna i seguenti tipi di esercizio:
1. 'caso_grammaticale': inserimento della corretta desinenza di caso (genitivo con preposizioni, dativo, strumentale, prepositivo, accusativo animato/inanimato).
2. 'aspetto_verbale': scelta tra imperfettivo e perfettivo in base al contesto temporale (durata, sequenza, risultato).
3. 'coniugazione': completamento con la forma del verbo coniugata al tempo e persona corretti.
4. 'completamento': completare una frase realistica e naturale con la parola corretta tra 4 opzioni di significato simile.
5. 'verbi_di_moto': uso corretto dei verbi di moto (con o senza prefisso) se la parola lo consente.

REQUISITI TASSATIVI:
- 'domanda': frase in russo con '_____' al posto della risposta corretta. Max 250 caratteri.
- 'opzione_corretta': la singola parola o breve locuzione corretta.
- 'distrattori': array di 3 opzioni plausibili ma errate (es. caso errato, aspetto errato, desinenza errata).
- 'spiegazione': breve spiegazione grammaticale in italiano del perché è corretta la risposta (MAX 180 CARATTERI!).

Rispondi ESCLUSIVAMENTE con un array JSON valido, senza markdown ```json:
[
  {{
    "parola": "nome_della_parola",
    "livello": "A2+" oppure "B1",
    "tipo": "caso_grammaticale" / "aspetto_verbale" / "coniugazione" / "completamento" / "verbi_di_moto",
    "domanda": "testo della frase con _____ da completare",
    "opzione_corretta": "parola corretta",
    "distrattori": ["distrattore1", "distrattore2", "distrattore3"],
    "spiegazione": "spiegazione grammaticale sintetica (max 180 caratteri)"
  }}
]"""
    return prompt


def generate_quizzes_with_gemini(words_batch, api_key):
    """Chiama Gemini per generare quiz strutturati."""
    try:
        from google import genai
    except ImportError:
        print("❌ google-genai non installato. Esegui: pip install google-genai")
        return []

    client = genai.Client(api_key=api_key)
    prompt = build_gemini_prompt(words_batch)

    models_to_try = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
    raw_text = None

    for model in models_to_try:
        try:
            print(f"🤖 Interrogo Gemini ({model}) per {len(words_batch)} vocaboli...")
            response = client.models.generate_content(
                model=model,
                contents=prompt,
            )
            if response and response.text:
                raw_text = response.text.strip()
                break
        except Exception as e:
            print(f"⚠️ Modello {model} fallito: {e}. Tento il prossimo...")

    if not raw_text:
        print("❌ Nessuna risposta ottenuta da Gemini.")
        return []

    # Pulizia eventuale markdown
    clean_json = raw_text
    if clean_json.startswith("```"):
        lines = clean_json.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        clean_json = "\n".join(lines).strip()

    try:
        data = json.loads(clean_json)
        if isinstance(data, list):
            return data
        print("⚠️ Il JSON restituito da Gemini non è una lista.")
        return []
    except json.JSONDecodeError as err:
        print(f"❌ Errore parsing JSON da Gemini: {err}")
        return []


def add_quizzes_to_database(df_quiz, quiz_items):
    """Randomizza le opzioni, determina l'indice corretto e aggiunge i record al database."""
    if not quiz_items:
        return df_quiz

    existing_count = len(df_quiz)
    new_rows = []

    for idx, item in enumerate(quiz_items, start=existing_count + 1):
        domanda = str(item.get("domanda", "")).strip()[:295]
        corretta = str(item.get("opzione_corretta", "")).strip()[:95]
        distrattori = [str(d).strip()[:95] for d in item.get("distrattori", [])[:3]]
        
        while len(distrattori) < 3:
            distrattori.append("—")

        # Mischia le 4 opzioni
        options = [corretta] + distrattori
        random.shuffle(options)
        correct_idx = options.index(corretta)

        spiegazione = str(item.get("spiegazione", "")).strip()[:195]

        new_rows.append({
            "id": f"Q{idx:04d}",
            "parola": str(item.get("parola", "")),
            "livello": str(item.get("livello", "A2+")),
            "tipo": str(item.get("tipo", "completamento")),
            "domanda": domanda,
            "opzione_0": options[0],
            "opzione_1": options[1],
            "opzione_2": options[2],
            "opzione_3": options[3],
            "corretta_idx": correct_idx,
            "spiegazione": spiegazione,
            "inviato": 0,
            "data_invio": "",
        })

    new_df = pd.DataFrame(new_rows)
    updated_df = pd.concat([df_quiz, new_df], ignore_index=True)
    return updated_df


def ensure_quiz_pool(df_parole, df_quiz, api_key, batch_size=10):
    """
    Verifica se ci sono nuove parole in parole.csv non ancora presenti in quiz_database.csv
    o se tutti i quiz sono stati esauriti.
    Rifornisce automaticamente il database con Gemini.
    """
    if df_parole.empty:
        return df_quiz

    # Parole già elaborate
    parole_elaborate = set(df_quiz["parola"].dropna().astype(str).unique())
    parole_disponibili = df_parole[~df_parole["Parola"].astype(str).isin(parole_elaborate)]

    # Conteggio quiz ancora da inviare
    unsent_count = len(df_quiz[df_quiz["inviato"] == 0]) if not df_quiz.empty else 0

    print(f"📊 Stato: {len(df_quiz)} quiz registrati, {unsent_count} da inviare, {len(parole_disponibili)} nuove parole da generare.")

    # Se ci sono nuove parole da elaborare e pochi quiz non inviati (< 5), generane un batch
    if not parole_disponibili.empty and (unsent_count < 5 or len(df_quiz) == 0):
        if not api_key:
            print("⚠️ GEMINI_API_KEY non impostata: impossibile generare nuovi quiz con Gemini.")
            return df_quiz

        da_generare = parole_disponibili.head(batch_size)
        print(f"✨ Generazione automatica di {len(da_generare)} nuovi quiz da parole.csv...")
        nuovi_quiz = generate_quizzes_with_gemini(da_generare, api_key)
        if nuovi_quiz:
            df_quiz = add_quizzes_to_database(df_quiz, nuovi_quiz)
            save_quiz_database(df_quiz)
            unsent_count = len(df_quiz[df_quiz["inviato"] == 0])

    # Se tutti i quiz sono stati completati (inviato == 1) e non ci sono più nuove parole
    if unsent_count == 0 and len(df_quiz) > 0:
        print("🔄 Tutti i quiz disponibili sono stati completati! Riavvio ciclo di revisione...")
        df_quiz["inviato"] = 0
        save_quiz_database(df_quiz)

    return df_quiz


def send_quiz_poll_telegram(quiz_row, bot_token, chat_id):
    """Invia il Quiz Poll nativo su Telegram."""
    base_url = f"https://api.telegram.org/bot{bot_token}"

    question = str(quiz_row["domanda"])
    livello = str(quiz_row.get("livello", "A2+"))
    tipo = str(quiz_row.get("tipo", "quiz")).replace("_", " ")

    # Intestazione con livello e tipo
    header = f"[{livello} • {tipo}]\n"
    if not question.startswith("["):
        full_question = header + question
    else:
        full_question = question
    
    # Limite Telegram question: 300 caratteri
    full_question = full_question[:300]

    options = [
        str(quiz_row["opzione_0"])[:100],
        str(quiz_row["opzione_1"])[:100],
        str(quiz_row["opzione_2"])[:100],
        str(quiz_row["opzione_3"])[:100],
    ]

    try:
        correct_option_id = int(quiz_row["corretta_idx"])
    except (ValueError, TypeError):
        correct_option_id = 0

    explanation = str(quiz_row.get("spiegazione", ""))[:200]

    payload = {
        "chat_id": chat_id,
        "question": full_question,
        "options": json.dumps(options),
        "type": "quiz",
        "correct_option_id": correct_option_id,
        "is_anonymous": False,
    }

    if explanation:
        payload["explanation"] = explanation

    print(f"🚀 Invio Quiz Poll a {chat_id} (ID: {quiz_row['id']} - Parola: {quiz_row.get('parola')})...")
    resp = requests.post(f"{base_url}/sendPoll", data=payload, timeout=20)

    if resp.status_code == 200:
        print("✅ Quiz Poll inviato con successo su Telegram!")
        return True
    else:
        print(f"❌ Errore Telegram API ({resp.status_code}): {resp.text}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Russian Telegram Quiz Bot")
    parser.add_argument("--action", choices=["run", "generate", "status"], default="run",
                        help="run = invia 1 quiz (e genera se necessario), generate = genera senza inviare, status = mostra statistiche")
    parser.add_argument("--batch-size", type=int, default=10, help="Numero di parole da elaborare con Gemini per batch")
    parser.add_argument("--chat-id", type=str, default=None, help="Telegram Chat ID (override)")
    args = parser.parse_args()

    bot_token = os.getenv("TELEGRAM_QUIZ_TOKEN") or os.getenv("TELEGRAM_TOKEN")
    api_key = os.getenv("GEMINI_API_KEY")
    chat_id = (
        args.chat_id
        or os.getenv("INPUT_CHAT_ID")
        or os.getenv("TELEGRAM_CHAT_ID")
        or os.getenv("TELEGRAM_CHAT_ID_ADMIN")
        or "516759354"
    )

    df_parole = load_parole()
    df_quiz = load_quiz_database()

    if args.action == "status":
        unsent = len(df_quiz[df_quiz["inviato"] == 0]) if not df_quiz.empty else 0
        sent = len(df_quiz[df_quiz["inviato"] == 1]) if not df_quiz.empty else 0
        print(f"📈 Parole in vocabolario: {len(df_parole)}")
        print(f"🎯 Quiz totali: {len(df_quiz)} (Inviati: {sent}, In coda: {unsent})")
        return

    if args.action == "generate":
        if not api_key:
            print("❌ GEMINI_API_KEY mancante.")
            sys.exit(1)
        df_quiz = ensure_quiz_pool(df_parole, df_quiz, api_key, batch_size=args.batch_size)
        return

    # Azione default: run (verifica rifornimento ed invia 1 quiz)
    df_quiz = ensure_quiz_pool(df_parole, df_quiz, api_key, batch_size=args.batch_size)

    # Trova il prossimo quiz non inviato
    pending = df_quiz[df_quiz["inviato"] == 0]
    if pending.empty:
        print("ℹ️ Nessun quiz disponibile da inviare.")
        return

    if not bot_token:
        print("⚠️ TELEGRAM_TOKEN non impostato. Esecuzione completata in modalità simulazione.")
        return

    if not chat_id:
        print("⚠️ TELEGRAM_CHAT_ID non trovato. Specificalo nei secret, via input o payload.")
        return

    prossimo_quiz = pending.iloc[0]
    idx_riga = pending.index[0]

    success = send_quiz_poll_telegram(prossimo_quiz, bot_token, chat_id)
    if success:
        df_quiz.loc[idx_riga, "inviato"] = 1
        df_quiz.loc[idx_riga, "data_invio"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_quiz_database(df_quiz)


if __name__ == "__main__":
    main()
