import sys
import csv
import time
import requests
import os

# --- CONFIGURATION ---
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")            # User token (Stories, polling, publish)
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")  # Page token (Reels container creation)
IG_USER_ID = "17841444282984648"                    # Instagram Business Account ID
FB_PAGE_ID = "741836139020105"                      # Facebook Page ID (per i Reels)
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

def preflight_check(video_url):
    """Verify Meta can reach the video URL before even trying to upload."""
    try:
        resp = requests.head(video_url, timeout=10, allow_redirects=True)
        content_type = resp.headers.get("Content-Type", "")
        print(f"🔍 Preflight: status={resp.status_code}, Content-Type={content_type}")
        if resp.status_code != 200:
            print(f"❌ URL returned {resp.status_code} — Meta cannot fetch this file.")
            return False
        if "video" not in content_type and "octet-stream" not in content_type:
            print(f"⚠️  Content-Type is '{content_type}' — Meta expects video/mp4")
            return False
        print("✅ URL is reachable and looks like a video.")
        return True
    except Exception as e:
        print(f"❌ Preflight failed: {e}")
        return False


def publish_video(word_file):
    video_url = f"{VIDEO_BASE_URL}{word_file}"
    print(f"\n--- Publishing: {video_url} ---")

    if not preflight_check(video_url):
        return False

    try:
        # Step 1: Create Reel container using Page Access Token
        create_resp = requests.post(
            f"{GRAPH_URL}/{FB_PAGE_ID}/media",
            data={
                "media_type": "REELS",
                "video_url": video_url,
                "caption": "",
                "access_token": PAGE_ACCESS_TOKEN
            }
        )
        print(f"📦 Container response ({create_resp.status_code}): {create_resp.text}")

        create_data = create_resp.json()
        creation_id = create_data.get("id")

        if not creation_id:
            print("❌ No container ID returned.")
            return False

        print(f"✅ Container ID: {creation_id}")

        # Step 2: Poll until FINISHED
        max_attempts = 20
        for attempt in range(1, max_attempts + 1):
            time.sleep(5)

            status_resp = requests.get(
                f"{GRAPH_URL}/{creation_id}",
                params={"fields": "status_code,status", "access_token": PAGE_ACCESS_TOKEN}
            )
            res_data = status_resp.json()
            status_code = res_data.get("status_code", "UNKNOWN")
            status_msg  = res_data.get("status", "")

            print(f"⏳ Attempt {attempt}: status_code={status_code!r}, status={status_msg!r}")

            if status_code == "FINISHED":
                print("✅ Container ready.")
                break
            elif status_code in ("ERROR", "EXPIRED") or "ERROR" in str(status_msg).upper():
                print(f"❌ Container failed — full response: {res_data}")
                return False

        else:
            print("❌ Timeout waiting for FINISHED.")
            return False

        # Step 3: Publish
        publish_resp = requests.post(
            f"{GRAPH_URL}/{FB_PAGE_ID}/media_publish",
            data={"creation_id": creation_id, "access_token": PAGE_ACCESS_TOKEN}
        )
        print(f"📤 Publish response ({publish_resp.status_code}): {publish_resp.text}")
        publish_resp.raise_for_status()
        return True

    except requests.exceptions.RequestException as e:
        print(f"❌ Request error: {e}")
        return False


# --- MAIN ---

def main():
    check_account()

    words = load_words()
    if not words:
        print("Cannot proceed: no words loaded.")
        return

    state = load_state()
    cycle = state["cycle"]
    step = state["step"]
    print(f"Current state — Cycle: {cycle}, Step: {step}")

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

    if not PAGE_ACCESS_TOKEN:
        print("ERROR: PAGE_ACCESS_TOKEN environment variable is not set.")
        sys.exit(1)

    main()
