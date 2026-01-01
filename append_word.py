# append_word.py

import pandas as pd
import sys
import os
from google import genai
from google.genai import types
import io 

# --- Funzione per la chiamata API di Gemini ---

def generate_csv_record(input_word):
    """
    Chiama l'API di Gemini per generare i dati del record CSV.
    Gestisce input sia in italiano che in russo.
    """
    # 1. Verifica che la chiave sia presente
    if 'GEMINI_API_KEY' not in os.environ:
        print("ATTENZIONE: La variabile d'ambiente GEMINI_API_KEY non è impostata.")
        return None
        
    # 2. Inizializzazione del client
    try:
        client = genai.Client()
    except Exception as e:
        raise ConnectionError(f"Errore di inizializzazione del client Gemini: {e}")

    # 3. Prompt ottimizzato per gestire la lingua di input e il formato CSV
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
        "Esempio se l'input è 'Mela' o 'яблоко':\n"
        "яблоко,mela,\"Frutto rotondo e dolce.\",Neutro. Plurale: яблоки.,Я ем яблоко. — Mangio una mela.,"
    )

    # 4. Chiamata API
    try:
        print(f"Chiamata a Gemini per elaborare '{input_word}'...")
        response = client.models.generate_content(
            model='gemini-2.0-flash', 
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1 # Temperatura ancora più bassa per massima precisione
            )
        )
        record_line = response.text.strip()
        return record_line

    except Exception as e:
        print(f"Errore nella chiamata API di Gemini per '{input_word}': {e}")
        return None

# --- Inizio dello Script Principale ---

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Errore: Inserisci una parola (russa o italiana) come argomento.")
        sys.exit(1)

    input_word = sys.argv[1]
    csv_file = 'parole.csv'
    column_names = ['Parola', 'Traduzione', 'Spiegazione (A1 russo)', 'Nota', 'Esempio', 'FileVideo']

    # 2. Genera il Record tramite Gemini
    csv_record_line = generate_csv_record(input_word)

    if not csv_record_line:
        print("Fallimento: Impossibile generare il record. Uscita.")
        sys.exit(1)

    print(f"Dati ricevuti: {csv_record_line}")

    # 3. Carica o crea il CSV
    try:
        df = pd.read_csv(csv_file)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        print(f"Inizializzazione di '{csv_file}'...")
        df = pd.DataFrame(columns=column_names)

    # 4. Conversione della riga ricevuta in DataFrame
    try:
        # Usiamo quotechar='"' per gestire correttamente i campi con virgolette
        new_row_df = pd.read_csv(io.StringIO(csv_record_line), 
                                 header=None, 
                                 names=column_names, 
                                 quotechar='"', 
                                 skipinitialspace=True)
    except Exception as e:
        print(f"Errore di parsing CSV: {e}")
        print("L'output di Gemini non era nel formato atteso.")
        sys.exit(1)

    # 5. Aggiunta del record e salvataggio
    df = pd.concat([df, new_row_df], ignore_index=True)
    df.to_csv(csv_file, index=False)

    # Estraiamo la parola russa per il messaggio finale di conferma
    parola_russa = new_row_df['Parola'].iloc[0]
    print(f"✅ Successo! Aggiunta la parola '{parola_russa}' a {csv_file}.")
