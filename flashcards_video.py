import sys
import csv
import time
import requests
import os
from datetime import date

# --- CONFIGURAZIONE ---
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN") # Token di accesso per l'API di Instagram
IG_USER_ID = "17841477441673896" # ID utente Instagram
API_VERSION = "v23.0"
GRAPH_URL = f"https://graph.facebook.com/{API_VERSION}"

# --- PERCORSI ASSOLUTI ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE = os.path.join(BASE_DIR, "parole.csv")
STATE_FILE = os.path.join(BASE_DIR, "stato_pubblicazione.csv")
VIDEO_BASE_URL = "http://roadtominds.altervista.org/Flashcards/"

# --- GESTIONE DATI (Minimalista: solo lettura FileVideo) ---

def load_words():
    """
    Carica le parole dal CSV. Mantiene tutti i campi per coerenza,
    ma l'unica cosa usata sarà 'FileVideo'.
    """
    words = []
    if not os.path.exists(CSV_FILE):
        print(f"ERRORE: File parole non trovato: {CSV_FILE}")
        return []
        
    with open(CSV_FILE, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            words.append(row)
    return words

# --- GESTIONE STATO DI PUBBLICAZIONE (cycle, step) ---

def load_state():
    """Carica lo stato corrente (cycle e step) dal file CSV."""
    if not os.path.exists(STATE_FILE):
        return {"cycle": 0, "step": 0}
    with open(STATE_FILE, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        try:
            row = next(reader)
            return {"cycle": int(row["cycle"]), "step": int(row["step"])}
        except StopIteration:
            return {"cycle": 0, "step": 0}

def save_state(state):
    """Salva il nuovo stato (cycle e step) nel file CSV."""
    with open(STATE_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['cycle', 'step'])
        writer.writeheader()
        writer.writerow(state)

# --- CALCOLO INDICE DELLA PAROLA ---

def calculate_word_index(cycle, step):
    """
    Calcola l'indice 0-based della parola da selezionare nella lista
    in base alla nuova logica, ignorando la lunghezza totale della lista.
    
    La formula è (cycle * 3) + 1 + offset_step.
    Viene ritornato l'indice 0-based da usare per la lista Python.
    """
    # Calcolo dell'offset (base 1) come da tua specifica:
    if 0 <= step < 3:
        offset_base_1 = 1
    elif 3 <= step < 6:
        offset_base_1 = 2
    elif 6 <= step < 9:
        offset_base_1 = 3
    elif step == 9: # Nello schema originale il passo 9 è incluso nella sezione 6-9
        offset_base_1 = 3
    elif step == 10:
        offset_base_1 = 4
    elif step == 11:
        offset_base_1 = 5
    elif step == 12:
        offset_base_1 = 6
    else:
        # Questo caso non dovrebbe succedere se la logica di reset è corretta
        offset_base_1 = 1

    # Calcolo dell'indice 1-based teorico (per la parola numero X)
    word_index_base_1 = (cycle * 3) + offset_base_1
    
    # Ritorna l'indice 0-based per la lista Python (Parola n.1 è indice 0)
    return word_index_base_1 - 1 

# --- PUBBLICAZIONE INSTAGRAM (REALE) ---

def publish_video(word_file):
    """
    Tenta di pubblicare un video su Instagram usando l'API Graph.
    """
    video_url = f"{VIDEO_BASE_URL}{word_file}"
    caption = f"Nuova Flashcard! Dettagli in: {video_url}"
    print(f"Tentativo di pubblicazione con video URL: {video_url}")
    
    # Step 1: Create Container
    try:
        create_resp = requests.post(
            f"{GRAPH_URL}/{IG_USER_ID}/media",
            data={
                "media_type": "STORIES",
                "video_url": video_url,
                "caption": caption,
                "access_token": ACCESS_TOKEN
            }
        )
        create_resp.raise_for_status() 
        creation_id = create_resp.json().get("id")
        
        if not creation_id:
            print("Errore creazione container:", create_resp.json())
            return False

        # Step 2: Check Status (Polling)
        while True:
            status_resp = requests.get(f"{GRAPH_URL}/{creation_id}",
                                     params={"fields": "status_code", "access_token": ACCESS_TOKEN})
            status_resp.raise_for_status()
            status = status_resp.json().get("status_code")
            
            if status == "FINISHED":
                break
            elif status in ["ERROR", "EXPIRED"]:
                print("Errore nel processing:", status_resp.json())
                return False
            
            time.sleep(5) 

        # Step 3: Publish
        publish_resp = requests.post(
            f"{GRAPH_URL}/{IG_USER_ID}/media_publish",
            data={"creation_id": creation_id, "access_token": ACCESS_TOKEN}
        )
        publish_resp.raise_for_status()
        print(f"✅ Pubblicato file {word_file}:", publish_resp.json())
        return True

    except requests.exceptions.RequestException as e:
        print(f"❌ Errore durante la pubblicazione: {e}")
        return False
    except Exception as e:
        print(f"❌ Errore generico: {e}")
        return False

# --- FUNZIONE PRINCIPALE ---

def main():
    # 1. Carica le parole e lo stato
    words = load_words()
    if not words:
        print("Impossibile procedere senza parole caricate.")
        return
        
    state = load_state()
    cycle = state["cycle"]
    step = state["step"]
    
    print(f"Stato Iniziale: Cycle={cycle}, Step={step}")

    # 2. Calcola l'indice 0-based da usare nella lista Python
    parola_index = calculate_word_index(cycle, step)
    
    if parola_index < 0:
        print("Errore di calcolo indice.")
        return
    
    # 3. Verifica che l'indice esista nella lista delle parole
    list_len = len(words)
    if parola_index >= list_len:
        print(f"⚠️ Indice calcolato ({parola_index}) fuori dai limiti della lista parole (lunghezza {list_len}).")
        print("Questo significa che il ciclo è andato oltre il numero di parole disponibili.")
        # Se l'indice è troppo grande, pubblichiamo l'ultima parola
        parola_index = list_len - 1 
        print(f"Usata l'ultima parola disponibile (Indice {parola_index}).")
    
    word_row = words[parola_index]
    
    # 4. Pubblica la parola
    word = word_row.get('Parola', 'N/A')
    file_video = word_row.get('FileVideo')
    
    print(f"✅ Pubblico parola: {word} (Indice calcolato: {parola_index})")
    
    if publish_video(file_video):
        print(f"✅ Pubblicazione completata per la parola: {word}")
        
        # 5. Aggiorna lo stato
        step += 1
        
        # Gestione del reset del ciclo (step = 12 nel tuo schema)
        if step > 12: 
            step = 0
            cycle += 1 
            print(f"🔁 Ciclo completato. Reset: Prossimo Cycle={cycle}, Prossimo Step={step}")
        else:
            print(f"➡️ Aggiornamento: Prossimo Cycle={cycle}, Prossimo Step={step}")

        # 6. Salva il nuovo stato
        save_state({"cycle": cycle, "step": step})
    else:
        print("❌ Pubblicazione fallita. Lo stato non viene aggiornato.")


if __name__ == "__main__":
    # Controllo del token di accesso all'avvio
    if not ACCESS_TOKEN:
        print("ERRORE: La variabile d'ambiente ACCESS_TOKEN non è impostata.")
        sys.exit(1)
        
    main()
