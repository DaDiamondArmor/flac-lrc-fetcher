# **Automated LRC Lyric Fetcher for FLAC Libraries**

This script automates the process of finding and downloading synchronized (.lrc) lyric files for your local FLAC music library. It scans a given directory recursively, reads metadata from each FLAC file, and fetches the corresponding lyrics from the [lrclib.net](https://lrclib.net/) database.  
It also romanizes Japanese and Korean lyrics with proper segmentation.

## **Features**

* **Recursive Scanning:** Traverses all subdirectories within your main music folder.  
* **Skips Existing Files:** Automatically skips any song that already has a corresponding .lrc file.  
* **Fast Concurrent Downloads:** Uses a pool of worker threads to download multiple lyric files simultaneously.  
* **Intelligent Fuzzy Searching:** If an exact match isn't found, it performs a "fuzzy" search and intelligently selects the best result based on track duration.  
* **Advanced Romaji Conversion:**  
  * Precisely converts **only** the Japanese (and Korean) character segments in a file, leaving English words, punctuation, and timestamps untouched.  
  * Can convert newly downloaded files on-the-fly.  
  * Can be run in a dedicated mode to convert all existing .lrc files in your library.  
* **Detailed Logging:** Creates a lrc-fetcher.log file to record all operations for easy debugging.  
* **Clear Progress & Summary:** Provides real-time feedback and a final summary of its work.
* **Embedding lyrics to FLAC:** Goes into the metadata and embeds the lyrics with the file, readable by some music players (like [Elisa](https://github.com/KDE/elisa)).
## **Requirements**

* Python 3.6+  
* The Python packages listed in requirements.txt:
  ```
   requests 
   mutagen  
   hangul-romanize  
   cutlet  
   unidic-lite
  ```
## **Setup & Installation**

It is highly recommended to run this script in a Python virtual environment to avoid conflicts with system-wide packages.

1. **Create a Virtual Environment:**  
   Open your terminal or command prompt in the directory where you saved the files and run:  
   ``` 
   python -m venv venv
   ```
2. **Activate the Environment:**  
   * **On macOS and Linux:**  
     ```
     source venv/bin/activate
     ```
   * **On Windows:**  
     ```
     .\\venv\\Scripts\\activate
     ```
Your prompt should change to show (venv) at the beginning.

3. **Install Required Packages:**  
   With the environment active, install the necessary libraries from the requirements.txt file:  
   ``` 
   pip install -r requirements.txt
   ```
## **Usage**

Run the script from your terminal, providing the path to your music library.  
**Important:** Always enclose the path in quotes (" ") to handle spaces correctly.

### **Standard Usage (Download Missing Only)**

This acts as a "Fast Mode". It only looks for FLAC files that have **no** lyrics and fetches them. It skips any existing lyric files without checking them.  
```
python lrc-fetcher.py "/path/to/your/music"
```
### **Upgrade Mode (Scan Unsynced Only)**

Use this mode if you want to fix your existing lyrics. It **ignores** missing lyrics and **only** looks for existing .lrc files that are unsynced (plain text). If found, it attempts to download a synced version to replace them.  
``` 
python lrc-fetcher.py "/path/to/your/music" --scan-unsynced
```
### **Downloading and Converting New Lyrics**

To download lyrics and immediately convert any Japanese lyrics to Romaji, add the `--romanize` flag (works with both modes above):  
``` 
python lrc-fetcher.py "/path/to/your/music" --romanize
```

### **Converting Existing Japanese Lyrics**

If you already have a library with Japanese .lrc files and want to convert them all to Romaji **in-place** (overwriting the originals), use the `--process-existing` flag. This will scan your library and **only** perform the conversion, without downloading any new files.  
```
python lrc-fetcher.py "/path/to/your/music" --process-existing
```
### **Embedding Lyrics to Files**

If you wish to embed the lyrics to be built in with your music, you can do so using the `--embed` flag.
```
python lrc-fetcher.py "/path/to/your/music" --embed
```

## **Deactivating the Environment**

When you are finished, you can exit the virtual environment by simply typing:  
``` 
deactivate
```
