import os
import sys
import requests
import re
import argparse
from mutagen.flac import FLAC
import concurrent.futures
import threading
import cutlet
from hangul_romanize.rule import academic
from hangul_romanize import Transliter

# --- Configuration ---
LRCLIB_API_URL = "https://lrclib.net/api/get"
LRCLIB_SEARCH_URL = "https://lrclib.net/api/search"
MAX_WORKERS = 10

# Initialize Cutlet globally
KATSU = cutlet.Cutlet()
KATSU.use_foreign_spelling = False

class ProgressTracker:
    def __init__(self):
        self.lrc_found = 0
        self.lrc_not_found = 0
        self.lrc_upgraded = 0
        self.romanized = 0
        self.embedded = 0
        self.errors = 0
        self.lock = threading.Lock()

    def increment_found(self):
        with self.lock: self.lrc_found += 1
    def increment_not_found(self):
        with self.lock: self.lrc_not_found += 1
    def increment_upgraded(self):
        with self.lock: self.lrc_upgraded += 1
    def increment_romanized(self):
        with self.lock: self.romanized +=1
    def increment_embedded(self):
        with self.lock: self.embedded += 1
    def increment_errors(self):
        with self.lock: self.errors += 1

def get_flac_metadata(filepath):
    try:
        audio = FLAC(filepath)
        artist = audio.get('artist', [None])[0]
        title = audio.get('title', [None])[0]
        duration = int(audio.info.length) if audio.info.length else None
        if not artist or not title:
            print(f"⚠️  Warning: Missing metadata in: {os.path.basename(filepath)}")
            return None, None, None
        return artist, title, duration
    except Exception as e:
        print(f"❌ Error reading metadata from {os.path.basename(filepath)}: {e}")
        return None, None, None

def check_if_content_synced(content):
    """Checks if a string contains LRC timestamps."""
    return bool(re.search(r'\[\d{2}:\d{2}(?:\.\d{2,3})?\]', content))

def check_if_file_synced(filepath):
    """Checks if an existing LRC file contains timestamps."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            # Read first 1000 chars to check for timestamps
            content = f.read(1000)
            return check_if_content_synced(content)
    except:
        return False

def romanize_text(text):
    """Detects language (Japanese or Korean) and romanizes accordingly."""
    RE_JAPANESE = re.compile(r'[ぁ-んァ-ン一-龯]')
    RE_KOREAN = re.compile(r'[\uAC00-\uD7A3]')

    if RE_KOREAN.search(text):
        transliter = Transliter(academic)
        return transliter.translit(text)
    elif RE_JAPANESE.search(text):
        return KATSU.romaji(text)
    return text

def convert_lrc_content(lrc_content):
    """Parses LRC content and romanizes lyrics (both synced and unsynced)."""
    converted_lines = []
    lrc_timestamp_regex = re.compile(r'(\[\d{2}:\d{2}(?:\.\d{2,3})?\])(.*)')
    metadata_regex = re.compile(r'^\[[a-zA-Z]+:')

    for line in lrc_content.strip().split('\n'):
        line = line.strip()
        if not line:
            converted_lines.append("")
            continue

        timestamp_match = lrc_timestamp_regex.match(line)
        if timestamp_match:
            timestamp = timestamp_match.group(1)
            lyric = timestamp_match.group(2).strip()
            if not lyric:
                converted_lines.append(timestamp)
            else:
                converted_lines.append(f"{timestamp} {romanize_text(lyric)}")
        elif metadata_regex.match(line):
            converted_lines.append(line)
        else:
            converted_lines.append(romanize_text(line))

    return "\n".join(converted_lines)

def embed_lyrics_into_flac(flac_path, lrc_content):
    """Embeds the provided lyrics string into the FLAC 'LYRICS' tag."""
    try:
        audio = FLAC(flac_path)
        audio['LYRICS'] = lrc_content
        audio.save()
        return True
    except Exception as e:
        print(f"❌ Error embedding lyrics into {os.path.basename(flac_path)}: {e}")
        return False

def fetch_lrc_from_lrclib(artist, title, duration):
    try:
        # Attempt 1: Exact Match
        params = {'artist_name': artist, 'track_name': title}
        if duration: params['duration'] = str(duration)
        response = requests.get(LRCLIB_API_URL, params=params, timeout=10)

        if response.status_code == 200:
            data = response.json()
            if data and data.get("syncedLyrics"):
                print(f"    -> Found exact match (synced) for '{title}'.")
                return data["syncedLyrics"]
            if data and data.get("plainLyrics"):
                print(f"    -> Found exact match (plain) for '{title}'.")
                return data["plainLyrics"]

        # Attempt 2: Fuzzy Search
        print(f"    -> Exact match failed or incomplete. Trying fuzzy search...")
        search_query = f"{artist} {title}"
        response = requests.get(LRCLIB_SEARCH_URL, params={"q": search_query}, timeout=10)

        if response.status_code == 200:
            results = response.json()
            if not results: return None

            valid_matches = []
            if duration:
                for r in results:
                    diff = abs(r.get("duration", 0) - duration)
                    if diff <= 3:
                        valid_matches.append((r, diff))

            if valid_matches:
                valid_matches.sort(key=lambda x: (1 if x[0].get("syncedLyrics") else 0, -x[1]), reverse=True)
                best_match = valid_matches[0][0]
            else:
                best_match = results[0]

            if best_match.get("syncedLyrics"):
                print(f"    -> Found synced lyrics via fuzzy search.")
                return best_match["syncedLyrics"]
            elif best_match.get("plainLyrics"):
                print(f"    -> Found plain lyrics via fuzzy search.")
                return best_match["plainLyrics"]

    except Exception as e:
        print(f"❌ Error fetching '{artist} - {title}': {e}")
    return None

def process_song(song_info, tracker, do_romanize, embed_lyrics):
    flac_path = song_info['flac_path']
    lrc_path = song_info['lrc_path']
    artist = song_info['artist']
    title = song_info['title']
    duration = song_info['duration']
    is_upgrade_attempt = song_info.get('upgrade_attempt', False)
    filename = os.path.basename(flac_path)

    print(f"🔎 Processing: {filename}")
    lrc_content = fetch_lrc_from_lrclib(artist, title, duration)

    if lrc_content:
        # Check if we are upgrading: Don't overwrite unsynced with unsynced
        content_is_synced = check_if_content_synced(lrc_content)

        if is_upgrade_attempt and not content_is_synced:
            print(f"    -> Only found unsynced lyrics online. Keeping existing unsynced file.")
            return

        try:
            # 1. Convert to Romanized text if requested
            if do_romanize:
                original_content = lrc_content
                lrc_content = convert_lrc_content(lrc_content)
                if lrc_content != original_content:
                    print(f"    -> Romanized lyrics.")
                    tracker.increment_romanized()

            # 2. Save to .lrc file
            with open(lrc_path, 'w', encoding='utf-8') as f:
                f.write(lrc_content)

            if is_upgrade_attempt:
                print(f"    -> 🆙 Upgraded to synced lyrics!")
                tracker.increment_upgraded()
            else:
                print(f"    -> Saved .lrc file.")
                tracker.increment_found()

            # 3. Embed into FLAC if requested
            if embed_lyrics:
                success = embed_lyrics_into_flac(flac_path, lrc_content)
                if success:
                    print(f"    -> Embedded lyrics into FLAC.")
                    tracker.increment_embedded()

        except IOError as e:
            print(f"❌ Error saving file for {filename}: {e}")
            tracker.increment_errors()
    else:
        print(f"🤷 No lyrics found for: {filename}")
        tracker.increment_not_found()

def process_existing_lrcs(music_dir, embed_lyrics):
    """Scans for existing .lrc files, romanizes them, and/or embeds them."""
    print("\n--- Processing Existing LRC Files ---")
    lrc_files_found = []
    for root, _, files in os.walk(music_dir):
        for filename in files:
            if filename.lower().endswith('.lrc'):
                lrc_files_found.append(os.path.join(root, filename))

    if not lrc_files_found:
        print("No .lrc files found.")
        return

    print(f"Found {len(lrc_files_found)} .lrc files.")
    converted_count = 0
    embedded_count = 0

    for lrc_path in lrc_files_found:
        flac_path = os.path.splitext(lrc_path)[0] + '.flac'

        try:
            with open(lrc_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Romanize logic
            if re.search(r'[ぁ-んァ-ン一-龯\uAC00-\uD7A3]', content):
                print(f"-> Romanizing: {os.path.basename(lrc_path)}")
                content = convert_lrc_content(content)
                with open(lrc_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                converted_count += 1

            # Embed logic
            if embed_lyrics and os.path.exists(flac_path):
                print(f"-> Embedding into: {os.path.basename(flac_path)}")
                embed_lyrics_into_flac(flac_path, content)
                embedded_count += 1

        except Exception as e:
            print(f"❌ Error processing {os.path.basename(lrc_path)}: {e}")

    print("\n--- Existing Files Summary ---")
    print(f"Romanized files: {converted_count}")
    print(f"Embedded into FLAC: {embedded_count}")
    print("------------------------------")

def process_music_library(music_dir, do_romanize, embed_lyrics, scan_unsynced):
    if not os.path.isdir(music_dir):
        print(f"❌ Error: Directory not found at '{music_dir}'")
        return

    mode_label = "Scanning for UNSYNCED UPGRADES" if scan_unsynced else "Scanning for MISSING LYRICS"
    print(f"--- Phase 1: {mode_label} ---")

    songs_to_process = []
    total_files = 0
    lrc_skipped = 0
    lrc_upgrades_needed = 0

    for root, _, files in os.walk(music_dir):
        for filename in files:
            if filename.lower().endswith('.flac'):
                total_files += 1
                flac_path = os.path.join(root, filename)
                lrc_path = os.path.splitext(flac_path)[0] + '.lrc'

                lrc_exists = os.path.exists(lrc_path)
                upgrade_attempt = False

                if scan_unsynced:
                    # Upgrade Mode: Only care if LRC exists and is unsynced
                    if lrc_exists:
                        if check_if_file_synced(lrc_path):
                            lrc_skipped += 1 # "Skipped (Already Synced)"
                            continue
                        else:
                            # Found unsynced file -> Mark for upgrade
                            upgrade_attempt = True
                            lrc_upgrades_needed += 1
                    else:
                        # LRC doesn't exist -> Skip (Don't fetch missing in this mode)
                        continue
                else:
                    # Default Mode: Only care if LRC is missing
                    if lrc_exists:
                        lrc_skipped += 1
                        continue
                    # Else: LRC missing -> Fetch new

                # If we reached here, we are processing this song
                if upgrade_attempt:
                     print(f"⚠️  Found unsynced lyrics for '{filename}'. Will try to upgrade.")

                artist, title, duration = get_flac_metadata(flac_path)
                if all([artist, title, duration]):
                    songs_to_process.append({
                        'flac_path': flac_path, 'lrc_path': lrc_path,
                        'artist': artist, 'title': title, 'duration': duration,
                        'upgrade_attempt': upgrade_attempt
                    })

    print(f"Scan complete. Found {len(songs_to_process)} songs to process.\n")
    if not songs_to_process:
        print("✨ No songs found matching current mode criteria.")
        return

    print(f"--- Phase 2: Fetching & Processing ({MAX_WORKERS} threads) ---")
    tracker = ProgressTracker()

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_song = {executor.submit(process_song, song, tracker, do_romanize, embed_lyrics): song for song in songs_to_process}
        for future in concurrent.futures.as_completed(future_to_song):
            try:
                future.result()
            except Exception as exc:
                print(f"❌ Exception: {exc}")
                tracker.increment_errors()

    print("\n--- Summary ---")
    print(f"Total FLAC files: {total_files}")
    if scan_unsynced:
        print(f"Skipped (Already Synced): {lrc_skipped}")
        print(f"Upgraded to Synced: {tracker.lrc_upgraded}")
    else:
        print(f"Skipped (Existing LRC): {lrc_skipped}")
        print(f"Downloaded New: {tracker.lrc_found}")

    if do_romanize: print(f"Romanized: {tracker.romanized}")
    if embed_lyrics: print(f"Embedded into FLAC: {tracker.embedded}")
    if scan_unsynced:
        print(f"Could not find upgrade: {tracker.lrc_not_found}")
    else:
        print(f"Not found: {tracker.lrc_not_found}")
    print("---------------")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch, romanize, and embed lyrics for FLAC files.")
    parser.add_argument("music_dir", help="The root directory of your music library.")

    # Flags
    parser.add_argument("--romanize", action="store_true", help="Convert Japanese (Romaji) and Korean (Romanized) lyrics.")
    parser.add_argument("--embed", action="store_true", help="Embed the lyrics (text/lrc) into the FLAC file metadata.")

    # Modes (Mutually exclusive logical flows)
    group = parser.add_argument_group('modes')
    group.add_argument("--process-existing", action="store_true", help="Local only: Scan existing LRC files to convert/embed them.")
    group.add_argument("--scan-unsynced", action="store_true", help="Upgrade only: Scan existing LRC files for unsynced lyrics and attempt to upgrade them. Ignores missing files.")

    args = parser.parse_args()

    if args.process_existing:
        process_existing_lrcs(args.music_dir, args.embed)
    else:
        process_music_library(args.music_dir, args.romanize, args.embed, args.scan_unsynced)
