import sys
import yt_dlp
import os

def download_audio(url):
    # We use a fixed filename 'input' so it's easy to pass to the next script.
    # yt-dlp will automatically add the .mp3 extension after conversion.
    filename = 'input'
    
    # Remove old file if it exists so we don't get 'input.mp3' and 'input (1).mp3'
    if os.path.exists('input.mp3'):
        os.remove('input.mp3')

    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'outtmpl': filename, # saves as input.webm/m4a first, then converts
        'quiet': False,
        'no_warnings': True,
    }

    print(f"Downloading and converting: {url}")
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        print(f"\nSuccess! File saved as: {filename}.mp3")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python get_audio.py <youtube_url>")
        sys.exit(1)
        
    download_audio(sys.argv[1])