# append_word.py

import pandas as pd
import sys
import os
from google import genai
from google.genai import types
import io # Necessario per leggere la stringa come CSV

# --- Funzione per la chiamata API di Gemini ---

def generate_csv_record(word):
    """
    Chiama l'API di Gemini per generare i dati del record CSV.
    Restituisce la stringa del record (es. "parola,traduzione,...").
    """
    # 1. Verifica che la chiave sia presente
    if 'GEMINI_API_KEY' not in os.environ:
        print("ATTENZIONE: La variabile d'ambiente GEMINI_API_KEY non è impostata.")
        return None
        
    # 2. Inizializzazione del client
    try:
        # La libreria genai.Client() legge automaticamente la variabile GEMINI_API_KEY dall'ambiente
        client = genai.Client()
    except Exception as e:
        # Solleva un errore se la connessione o l'inizializzazione falliscono
        raise ConnectionError(f"Errore di inizializzazione del client Gemini: {e}")

    # 3. Il prompt cruciale per ottenere un output CSV pulito
    # Si mantiene il prompt che forza il modello a restituire un formato rigoroso.
    prompt = (
        f"Genera i campi di un record per un file CSV, usando la parola russa '{word}'. "
        "I campi devono essere: Parola, Traduzione, Spiegazione (A1 russo), Nota, Esempio, FileVideo. "
        "La tua risposta deve contenere solo i valori separati da virgole, senza intestazioni. "
        "Includi virgolette doppie attorno ai campi come 'Spiegazione (A1 russo)' se contengono virgole. "
        "Esempio di output desiderato: лицо,viso,\"Передняя часть головы: глаза, нос, рот.\",Neutro. Significa sia 'volto' sia 'persona' in certi contesti.,У неё красивое лицо. — Ha un bel viso.,\n"
        "Non includere nessun altro testo, intestazione o spiegazione."
    )

    # 4. Chiamata API
    try:
        print(f"Chiamata a Gemini per generare i dati per '{word}'...")
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2 # Bassa temperatura per risposte più deterministiche
            )
        )
        # Rimuove spazi bianchi o newline
        record_line = response.text.strip()
        return record_line

    except Exception as e:
        print(f"Errore nella chiamata API di Gemini per la parola '{word}': {e}")
        return None

# --- Inizio dello Script Principale ---

# 1. Setup e Argomenti
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Errore: La parola non è stata passata come argomento.")
        sys.exit(1)

    new_word = sys.argv[1]
    csv_file = 'test_parole.csv'
    column_names = ['Parola', 'Traduzione', 'Spiegazione (A1 russo)', 'Nota', 'Esempio', 'FileVideo']

    # 2. Genera il Record Completo tramite Gemini
    csv_record_line = generate_csv_record(new_word)

    if csv_record_line is None:
        print("Fallimento: Impossibile generare il record completo. Uscita dallo script.")
        sys.exit(1)

    print(f"Record generato da Gemini: {csv_record_line}")

    # 3. Carica il CSV esistente
    try:
        # Prova a leggere il file esistente (con header)
        df = pd.read_csv(csv_file)
    except FileNotFoundError:
        # Se il file non esiste, crea un nuovo DataFrame con l'intestazione completa
        print(f"File '{csv_file}' non trovato. Creazione di un nuovo file.")
        df = pd.DataFrame(columns=column_names)
    except pd.errors.EmptyDataError:
        # Se il file esiste ma è vuoto, crea un nuovo DataFrame con l'intestazione
        print(f"File '{csv_file}' vuoto. Inizializzazione del DataFrame.")
        df = pd.DataFrame(columns=column_names)


    # 4. Crea il nuovo DataFrame per l'aggiunta dal record generato
    try:
        # Usiamo io.StringIO per trattare la stringa CSV come un file
        # header=None: indica che la stringa non ha l'intestazione
        # names=column_names: usa i nomi di colonna definiti per l'assegnazione
        new_row_df = pd.read_csv(io.StringIO(csv_record_line), header=None, names=column_names)
    except Exception as e:
        print(f"Errore nella conversione del record CSV in DataFrame: {e}")
        print("Assicurati che l'output di Gemini abbia il formato e il numero di campi corretto (6 campi).")
        sys.exit(1)


    # 5. Aggiungi la nuova riga
    df = pd.concat([df, new_row_df], ignore_index=True)
    print("Record aggiunto al DataFrame.")

    # 6. Salva il file CSV aggiornato
    df.to_csv(csv_file, index=False)

    print(f"✅ Record per la parola '{new_word}' aggiunto con successo a {csv_file}.")
