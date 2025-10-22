import sys
import csv
import datetime
import time
import requests
import os

ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")

# --- CONFIG ---
IG_USER_ID = "17841477441673896"
API_VERSION = "v23.0"
GRAPH_URL = f"https://graph.facebook.com/{API_VERSION}"

# --- PERCORSI ASSOLUTI ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE = os.path.join(BASE_DIR, "russo_parole.csv")
VIDEO_BASE_URL = "http://roadtominds.altervista.org/Flashcards/"

NUOVE_AL_GIORNO = 3
RIPASSO_AL_GIORNO = 3
PUBBLICAZIONI_NUOVA = 3

RESET_FILE = os.path.join(BASE_DIR, "last_reset.txt") # File kept for structure consistency
STATE_FILE = os.path.join(BASE_DIR, "stato_pubblicazione.csv")

# --- Lettura parole ---
def load_words():
    words = []
    with open(CSV_FILE, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Ensure fields exist and are integers
            row['RipetizioniTotali'] = int(row.get('RipetizioniTotali', 0))
            row['OggiPubblicazioni'] = int(row.get('OggiPubblicazioni', 0))
            row['DaRipassareDomani'] = int(row.get('DaRipassareDomani', 0))
            words.append(row)
    return words

# --- Scrittura parole ---
def save_words(words):
    fieldnames = ['Parola','Traduzione','Spiegazione (A1 russo)','Nota','Esempio',
                  'RipetizioniTotali','OggiPubblicazioni','Tipo','DaRipassareDomani','FileVideo']
    with open(CSV_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(words)

# --- Stato pubblicazione ---
def load_state():
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
    with open(STATE_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['cycle', 'step'])
        writer.writeheader()
        writer.writerow(state)

# --- Azzeramento campi (Non più 'giornaliero', ma basato sulla logica di pubblicazione) ---
def reset_words_for_selection(words):
    """
    Resets the 'OggiPubblicazioni' count for eligible words, decoupling from the calendar day.
    """
    print("Azzeramento contatori per la selezione...")
    for w in words:
        # Reset new words' publication count
        if w['Tipo'] == 'nuova':
            w['OggiPubblicazioni'] = 0
        # Reset review words' publication count
        if w['DaRipassareDomani'] == 1:
            w['OggiPubblicazioni'] = 0
    
    # Write a date to the RESET_FILE just to keep the file updated.
    with open(RESET_FILE, 'w') as f:
        f.write(str(datetime.date.today()))
        
    return words

# --- Selezione parole ---
def select_words(words):
    to_publish = []
    # Only 'nuova' words not fully published today
    nuove = [w for w in words if w['Tipo'] == 'nuova' and w['OggiPubblicazioni'] < PUBBLICAZIONI_NUOVA]
    # Only review words not yet published today
    ripasso = [w for w in words if w['DaRipassareDomani'] == 1 and w['OggiPubblicazioni'] < 1]

    # Select up to NUOVE_AL_GIORNO new words
    count_nuove = min(len(nuove), NUOVE_AL_GIORNO)
    to_publish.extend(nuove[:count_nuove])

    # Select up to RIPASSO_AL_GIORNO review words
    count_ripasso = min(len(ripasso), RIPASSO_AL_GIORNO)
    to_publish.extend(ripasso[:count_ripasso])

    return to_publish

# --- Pubblicazione Instagram ---
def publish_video(word_file):
    video_url = f"{VIDEO_BASE_URL}{word_file}"
    caption = ""
    print(f"Tentativo di pubblicazione con video URL: {video_url}")
    
    # Step 1: Create Container
    create_resp = requests.post(
        f"{GRAPH_URL}/{IG_USER_ID}/media",
        data={
            "media_type": "STORIES",
            "video_url": video_url,
            "caption": caption,
            "access_token": ACCESS_TOKEN
        }
    )
    creation_id = create_resp.json().get("id")
    if not creation_id:
        print("Errore creazione container:", create_resp.json())
        return False

    # Step 2: Check Status
    while True:
        status_resp = requests.get(f"{GRAPH_URL}/{creation_id}",
                                 params={"fields": "status_code", "access_token": ACCESS_TOKEN})
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
    print(f"Pubblicato file {word_file}:", publish_resp.json())
    return True

# --- MAIN RIVISTO ---
def main():
    words = load_words()
    
    # Reset counts to make words eligible for selection
    words = reset_words_for_selection(words) 
    save_words(words)
    
    to_publish = select_words(words)
    state = load_state()

    cycle = state["cycle"]
    step = state["step"]
    
    # New base shift: +2 per cycle
    base_shift = cycle * 2

    # New 12-step sequence of relative indices:
    # 3x index 3 (fourth word), 3x index 4 (fifth word), 
    # 1x index 0, 1x index 1, 1x index 2, 
    # 3x index 5 (sixth word)
    sequence_relative_indices = [3, 3, 3, 4, 4, 4, 0, 1, 2, 5, 5, 5]

    if not to_publish:
        print("Nessuna parola da pubblicare.")
        return
    
    list_len = len(to_publish)
    
    # Calculate the base word index for the current step and cycle
    relative_index = sequence_relative_indices[step % len(sequence_relative_indices)]
    
    # Calculate the final index, applying the cycle shift and list modulo
    word_index_base = relative_index + base_shift
    parola_index = word_index_base % list_len
    
    word_row = to_publish[parola_index]

    # --- pubblica UNA parola ---
    word = word_row['Parola']
    print(f"✅ Pubblico parola: {word} (Indice calcolato: {parola_index})")
    
    if publish_video(word_row['FileVideo']):
        word_row['OggiPubblicazioni'] += 1
        
        # Mark as ready for review once published enough times
        if word_row['Tipo'] == 'nuova' and word_row['OggiPubblicazioni'] >= PUBBLICAZIONI_NUOVA:
            word_row['DaRipassareDomani'] = 1
            
        word_row['RipetizioniTotali'] += 1
        save_words(words)

    # Aggiorna stato
    step += 1
    if step >= 12: # Full 12-step cycle complete
        step = 0
        cycle += 1 # Move to the next cycle (which increases the base_shift)
        
    save_state({"cycle": cycle, "step": step})
    print(f"🔁 Prossimo ciclo: {cycle}, step: {step}")

if __name__ == "__main__":
    # Check for ACCESS_TOKEN at startup
    if not ACCESS_TOKEN:
        print("ERRORE: La variabile d'ambiente ACCESS_TOKEN non è impostata.")
        sys.exit(1)
        
    main()
