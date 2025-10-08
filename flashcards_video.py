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

RESET_FILE = os.path.join(BASE_DIR, "last_reset.txt")
STATE_FILE = os.path.join(BASE_DIR, "stato_pubblicazione.csv")

# --- Lettura parole ---
def load_words():
    words = []
    with open(CSV_FILE, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            row['RipetizioniTotali'] = int(row['RipetizioniTotali'])
            row['OggiPubblicazioni'] = int(row['OggiPubblicazioni'])
            row['DaRipassareDomani'] = int(row['DaRipassareDomani'])
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
        row = next(reader)
        return {"cycle": int(row["cycle"]), "step": int(row["step"])}

def save_state(state):
    with open(STATE_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['cycle', 'step'])
        writer.writeheader()
        writer.writerow(state)

# --- Reset giornaliero ---
def reset_daily(words):
    today = datetime.date.today()
    last_reset = None
    if os.path.exists(RESET_FILE):
        with open(RESET_FILE, 'r') as f:
            last_reset_str = f.read().strip()
            if last_reset_str:
                last_reset = datetime.datetime.strptime(last_reset_str, "%Y-%m-%d").date()
    if last_reset != today:
        print("Reset giornaliero...")
        for w in words:
            if w['Tipo'] == 'nuova':
                w['OggiPubblicazioni'] = 0
            if w['DaRipassareDomani'] == 1:
                w['OggiPubblicazioni'] = 0
        with open(RESET_FILE, 'w') as f:
            f.write(str(today))
    return words

# --- Selezione parole ---
def select_words(words):
    to_publish = []
    nuove = [w for w in words if w['Tipo'] == 'nuova' and w['OggiPubblicazioni'] < PUBBLICAZIONI_NUOVA]
    ripasso = [w for w in words if w['DaRipassareDomani'] == 1 and w['OggiPubblicazioni'] < 1]

    count_nuove = min(len(nuove), NUOVE_AL_GIORNO)
    to_publish.extend(nuove[:count_nuove])

    count_ripasso = min(len(ripasso), RIPASSO_AL_GIORNO)
    to_publish.extend(ripasso[:count_ripasso])

    return to_publish

# --- Pubblicazione Instagram ---
def publish_video(word_number):
    video_url = f"{VIDEO_BASE_URL}{word_number}"
    caption = ""
    print(video_url)
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

    publish_resp = requests.post(
        f"{GRAPH_URL}/{IG_USER_ID}/media_publish",
        data={"creation_id": creation_id, "access_token": ACCESS_TOKEN}
    )
    print(f"Pubblicato {word_number}:", publish_resp.json())
    return True

# --- MAIN ---
def main():
    words = load_words()
    words = reset_daily(words)
    to_publish = select_words(words)
    state = load_state()

    cycle = state["cycle"]
    step = state["step"]
    base = cycle * 3

    # sequenza 12-step per ogni ciclo
    sequence = [base+3]*3 + [base+4]*3 + [base+5]*3 + [base+0, base+1, base+2]
    parola_index = sequence[step % len(sequence)] % len(to_publish)

    if not to_publish:
        print("Nessuna parola da pubblicare oggi.")
        return

    word_row = to_publish[parola_index]

    # --- pubblica UNA parola ---
    word = word_row['Parola']
    print(f"✅ Pubblico parola: {word}")
    if publish_video(word_row['FileVideo']):
        word_row['OggiPubblicazioni'] += 1
        if word_row['Tipo'] == 'nuova' and word_row['OggiPubblicazioni'] >= PUBBLICAZIONI_NUOVA:
            word_row['DaRipassareDomani'] = 1
        word_row['RipetizioniTotali'] += 1
        save_words(words)

    # aggiorna stato
    step += 1
    if step >= 12:
        step = 0
        cycle += 1
    save_state({"cycle": cycle, "step": step})
    print(f"🔁 Prossimo ciclo: {cycle}, step: {step}")

if __name__ == "__main__":
    main()
