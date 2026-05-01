import sys
import csv
import time
import requests
import os

# --- CONFIGURATION ---
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")  # Instagram API access token
IG_USER_ID = "17841444282984648"          # Instagram user ID
API_VERSION = "v21.0"
GRAPH_URL = f"https://graph.facebook.com/{API_VERSION}"

# --- ABSOLUTE PATHS ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE = os.path.join(BASE_DIR, "parole.csv")
STATE_FILE = os.path.join(BASE_DIR, "stato_pubblicazione.csv")
VIDEO_BASE_URL = "https://roadtominds.altervista.org/Flashcards/"


# --- DATA LOADING ---

def check_account():
    """Verifies token identity and associated pages."""
    resp = requests.get(
        f"{GRAPH_URL}/me",
        params={"fields": "id,name", "access_token": ACCESS_TOKEN}
    )
    print("ME:", resp.json())

    resp2 = requests.get(
        f"{GRAPH_URL}/me/accounts",
        params={"access_token": ACCESS_TOKEN}
    )
    print("PAGES:", resp2.json())


def load_words():
    """Loads words from the CSV file. Only 'FileVideo' is used for publishing."""
    words = []
    if not os.path.exists(CSV_FILE):
        print(f"ERROR: Words file not found: {CSV_FILE}")
        return []

    with open(CSV_FILE, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            words.append(row)
    return words


# --- PUBLICATION STATE MANAGEMENT (cycle, step) ---

def load_state():
    """Loads the current publication state (cycle and step) from the state CSV."""
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
    """Saves the updated publication state (cycle and step) to the state CSV."""
    with open(STATE_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['cycle', 'step'])
        writer.writeheader()
        writer.writerow(state)


# --- WORD INDEX CALCULATION ---

def calculate_word_index(cycle, step):
    """
    Returns the 0-based index of the word to publish, based on the current
    cycle and step using the following offset logic:

        steps  0–2  → offset 1
        steps  3–5  → offset 2
        steps  6–9  → offset 3
        step   10   → offset 4
        step   11   → offset 5
        step   12   → offset 6

    Formula: word_index (1-based) = (cycle * 3) + offset
    """
    if 0 <= step < 3:
        offset = 1
    elif 3 <= step < 6:
        offset = 2
    elif 6 <= step <= 9:
        offset = 3
    elif step == 10:
        offset = 4
    elif step == 11:
        offset = 5
    elif step == 12:
        offset = 6
    else:
        offset = 1  # Fallback — should not occur with correct reset logic

    return (cycle * 3) + offset - 1  # Convert to 0-based index


# --- INSTAGRAM PUBLISHING ---

def publish_video(word_file):
    """
    Publishes a video to Instagram Stories via the Graph API.
    Steps: create media container → poll until ready → publish.
    Returns True on success, False on failure.
    """
    video_url = f"{VIDEO_BASE_URL}{word_file}"
    print(f"Publishing video: {video_url}")

    try:
        # Step 1: Create media container
        create_resp = requests.post(
            f"{GRAPH_URL}/{IG_USER_ID}/media",
            data={
                "media_type": "STORIES",
                "video_url": video_url,
                "access_token": ACCESS_TOKEN
            }
        )
        create_resp.raise_for_status()
        creation_id = create_resp.json().get("id")

        if not creation_id:
            print("Container creation error:", create_resp.json())
            return False

        # Step 2: Poll until container status is FINISHED
        max_attempts = 20
        for attempt in range(1, max_attempts + 1):
            print(f"⏳ Polling attempt {attempt}/{max_attempts}...")

            status_resp = requests.get(
                f"{GRAPH_URL}/{creation_id}",
                params={"fields": "status_code,status", "access_token": ACCESS_TOKEN}
            )

            if not status_resp.ok:
                print(f"❌ Polling error: {status_resp.json()}")
                return False

            res_data = status_resp.json()
            status = res_data.get("status_code") or res_data.get("status")

            if status == "FINISHED":
                print("✅ Container ready.")
                break
            elif status in ["ERROR", "EXPIRED"]:
                print(f"❌ Container error: {res_data}")
                return False
            else:
                time.sleep(5)
        else:
            print("❌ Timeout: container did not reach FINISHED status.")
            return False

        # Step 3: Publish the container
        publish_resp = requests.post(
            f"{GRAPH_URL}/{IG_USER_ID}/media_publish",
            data={"creation_id": creation_id, "access_token": ACCESS_TOKEN}
        )
        publish_resp.raise_for_status()
        print(f"✅ Published {word_file}:", publish_resp.json())
        return True

    except requests.exceptions.RequestException as e:
        print(f"❌ Request error: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False


# --- MAIN ---

def main():
    check_account()

    # Load words and current state
    words = load_words()
    if not words:
        print("Cannot proceed: no words loaded.")
        return

    state = load_state()
    cycle = state["cycle"]
    step = state["step"]
    print(f"Current state — Cycle: {cycle}, Step: {step}")

    # Determine which word to publish
    parola_index = calculate_word_index(cycle, step)

    if parola_index < 0:
        print("Index calculation error.")
        return

    list_len = len(words)
    if parola_index >= list_len:
        print(f"⚠️ Calculated index ({parola_index}) exceeds word list length ({list_len}). Using last word.")
        parola_index = list_len - 1

    word_row = words[parola_index]
    word = word_row.get('Parola', 'N/A')
    file_video = word_row.get('FileVideo')

    print(f"Publishing word: {word} (index: {parola_index})")

    if publish_video(file_video):
        print(f"✅ Successfully published: {word}")

        # Advance step, reset cycle if complete
        step += 1
        if step > 12:
            step = 0
            cycle += 1
            print(f"🔁 Cycle complete. Next → Cycle: {cycle}, Step: {step}")
        else:
            print(f"➡️ Next → Cycle: {cycle}, Step: {step}")

        save_state({"cycle": cycle, "step": step})
    else:
        print("❌ Publishing failed. State not updated.")


if __name__ == "__main__":
    if not ACCESS_TOKEN:
        print("ERROR: ACCESS_TOKEN environment variable is not set.")
        sys.exit(1)

    main()
