"""Publishes the cinememe flashcards to Instagram Stories, one per trigger.

Ordering is a "quadruple chain": every card is shown 4 times, with 2-3 other
cards in between each repetition, then it retires and a new card takes its
place. When every card has been through its 4 showings the cycle restarts.

Same secret and same trigger style as flashcards_video.py.
"""

import csv
import os
import sys
import time

import requests

# --- CONFIGURATION ---
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")  # Instagram API access token
IG_USER_ID = "17841444282984648"          # Instagram user ID
API_VERSION = "v21.0"
GRAPH_URL = f"https://graph.facebook.com/{API_VERSION}"

REPEATS = 4          # how many times each card is shown

# The chain schedule. Cards enter in pairs: the pair starts every 8 posts and the
# second card of the pair enters 2 posts after the first. Each card is then shown
# at these offsets from its entry, so the spacing between its showings runs
# 3, 2, 3 other cards. This is the only shape that keeps every slot filled while
# letting the spacing vary between 2 and 3.
PAIR_PERIOD = 8
PAIR_STAGGER = 2
SHOW_OFFSETS = (0, 4, 7, 11)

# --- ABSOLUTE PATHS ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CARDS_DIR = os.path.join(BASE_DIR, "cinememes")
STATE_FILE = os.path.join(BASE_DIR, "stato_cinememes.csv")
IMAGE_BASE_URL = "https://raw.githubusercontent.com/gfusarbassini/flashcards-video-bot/main/cinememes/"


# --- DATA LOADING ---

def load_cards():
    """Returns the sorted list of card filenames (cinememe_01.png, ...)."""
    if not os.path.isdir(CARDS_DIR):
        print(f"ERROR: cards folder not found: {CARDS_DIR}")
        return []
    cards = sorted(
        f for f in os.listdir(CARDS_DIR)
        if f.lower().endswith(".png") and f.startswith("cinememe_")
    )
    if not cards:
        print(f"ERROR: no cards found in {CARDS_DIR}")
    return cards


# --- ORDERING: THE QUADRUPLE CHAIN ---

def build_sequence(n_cards):
    """Builds the full publication order for one cycle.

    Each card claims 4 slots on a timeline (its entry point plus SHOW_OFFSETS).
    Cards enter staggered, so at any moment three different cards are in
    rotation: one is on its way out while a fresh one has just come in. The
    slots are then read in order, which gives the interleaved chain.

    Returns a list of card indices, each appearing REPEATS times.
    """
    if n_cards == 0:
        return []
    if n_cards < 4:
        # Too few cards to interleave anything; just repeat them in order.
        return [i for _ in range(REPEATS) for i in range(n_cards)]

    # One "run" is a card's 4 showings. Runs are placed in pairs, so an even
    # number of runs is needed for the schedule to close on itself. With an odd
    # deck each card gets two runs per cycle, which makes the count even.
    runs = list(range(n_cards)) * (1 if n_cards % 2 == 0 else 2)
    length = REPEATS * len(runs)

    slots = {}
    for run_index, card in enumerate(runs):
        entry = (run_index // 2) * PAIR_PERIOD + (run_index % 2) * PAIR_STAGGER
        for off in SHOW_OFFSETS:
            slots[(entry + off) % length] = card

    if len(slots) != length:
        # Should not happen, but never publish a schedule with holes in it.
        raise RuntimeError(f"schedule failed to fill {length} slots for {n_cards} cards")

    return [slots[i] for i in range(length)]


# --- PUBLICATION STATE MANAGEMENT (cycle, step) ---

def load_state():
    """Loads the current publication state (cycle and step)."""
    if not os.path.exists(STATE_FILE):
        return {"cycle": 0, "step": 0}
    with open(STATE_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        try:
            row = next(reader)
            return {"cycle": int(row["cycle"]), "step": int(row["step"])}
        except (StopIteration, KeyError, ValueError):
            return {"cycle": 0, "step": 0}


def save_state(state):
    """Saves the updated publication state."""
    with open(STATE_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["cycle", "step"])
        writer.writeheader()
        writer.writerow(state)


# --- INSTAGRAM PUBLISHING ---

def check_account():
    """Verifies token identity and associated pages."""
    resp = requests.get(
        f"{GRAPH_URL}/me",
        params={"fields": "id,name", "access_token": ACCESS_TOKEN},
    )
    print("ME:", resp.json())


def preflight_check(image_url):
    """Verify Meta can reach the image URL before even trying to upload."""
    try:
        resp = requests.head(image_url, timeout=10, allow_redirects=True)
        content_type = resp.headers.get("Content-Type", "")
        print(f"🔍 Preflight: status={resp.status_code}, Content-Type={content_type}")
        if resp.status_code != 200:
            print(f"❌ URL returned {resp.status_code} — Meta cannot fetch this file.")
            return False
        if "image" not in content_type and "octet-stream" not in content_type:
            print(f"⚠️  Content-Type is '{content_type}' — Meta expects an image")
            return False
        print("✅ URL is reachable and looks like an image.")
        return True
    except requests.exceptions.RequestException as e:
        print(f"❌ Preflight failed: {e}")
        return False


def publish_story(card_file):
    """Publishes one card as an Instagram Story.

    Returns (result, reason) where reason is "ok", "preflight_failed"
    or "upload_failed".
    """
    image_url = f"{IMAGE_BASE_URL}{card_file}"
    print(f"\n--- Publishing: {image_url} ---")

    if not preflight_check(image_url):
        return False, "preflight_failed"

    try:
        # Step 1: Create container
        create_resp = requests.post(
            f"{GRAPH_URL}/{IG_USER_ID}/media",
            data={
                "media_type": "STORIES",
                "image_url": image_url,
                "access_token": ACCESS_TOKEN,
            },
        )
        print(f"📦 Container response ({create_resp.status_code}): {create_resp.text}")

        creation_id = create_resp.json().get("id")
        if not creation_id:
            print("❌ No container ID returned.")
            return False, "upload_failed"

        print(f"✅ Container ID: {creation_id}")

        # Step 2: Poll until the container is ready (images are usually instant)
        max_attempts = 12
        for attempt in range(1, max_attempts + 1):
            time.sleep(3)

            status_resp = requests.get(
                f"{GRAPH_URL}/{creation_id}",
                params={"fields": "status_code,status", "access_token": ACCESS_TOKEN},
            )
            res_data = status_resp.json()
            status_code = res_data.get("status_code", "UNKNOWN")
            status_msg = res_data.get("status", "")

            print(f"⏳ Attempt {attempt}: status_code={status_code!r}, status={status_msg!r}")

            if status_code == "FINISHED":
                print("✅ Container ready.")
                break
            if status_code in ("ERROR", "EXPIRED") or "ERROR" in str(status_msg).upper():
                print(f"❌ Container failed — full response: {res_data}")
                return False, "upload_failed"
        else:
            print("❌ Timeout waiting for FINISHED.")
            return False, "upload_failed"

        # Step 3: Publish
        publish_resp = requests.post(
            f"{GRAPH_URL}/{IG_USER_ID}/media_publish",
            data={"creation_id": creation_id, "access_token": ACCESS_TOKEN},
        )
        print(f"📤 Publish response ({publish_resp.status_code}): {publish_resp.text}")
        publish_resp.raise_for_status()
        return True, "ok"

    except requests.exceptions.RequestException as e:
        print(f"❌ Request error: {e}")
        return False, "upload_failed"


# --- MAIN ---

def main():
    check_account()

    cards = load_cards()
    if not cards:
        print("Cannot proceed: no cards loaded.")
        return

    sequence = build_sequence(len(cards))
    print(f"Loaded {len(cards)} cards — cycle is {len(sequence)} stories long.")

    state = load_state()
    cycle, step = state["cycle"], state["step"]

    # A card added or removed changes the cycle length; clamp instead of crashing.
    if step >= len(sequence):
        print(f"↩️ Step {step} is past the end of the cycle. Restarting the round.")
        step, cycle = 0, cycle + 1

    print(f"Current state — Cycle: {cycle}, Step: {step}")

    card_index = sequence[step]
    card_file = cards[card_index]
    showing = sequence[: step + 1].count(card_index)
    print(f"Publishing {card_file} (card {card_index + 1}/{len(cards)}, showing {showing}/{REPEATS})")

    result, reason = publish_story(card_file)

    if not result:
        if reason == "preflight_failed":
            print(f"🗑️ Card not reachable: {card_file}. Skipping this step.")
            # Still advance, otherwise a broken file blocks the rotation forever.
        else:
            print(f"❌ Publishing failed for '{card_file}'. Stopping — state not updated.")
            return
    else:
        print(f"✅ Successfully published: {card_file}")

    step += 1
    if step >= len(sequence):
        step = 0
        cycle += 1
        print(f"🔁 Round complete. Next → Cycle: {cycle}, Step: {step}")
    else:
        print(f"➡️ Next → Cycle: {cycle}, Step: {step}")

    save_state({"cycle": cycle, "step": step})


if __name__ == "__main__":
    if not ACCESS_TOKEN:
        print("ERROR: ACCESS_TOKEN environment variable is not set.")
        sys.exit(1)

    main()
