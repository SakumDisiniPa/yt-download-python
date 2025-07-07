from flask import Flask, render_template, request, send_file, jsonify
from flask_socketio import SocketIO
from flask_minify import minify
import yt_dlp
import os
import threading
import time
import uuid
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import re
import zipfile
import shutil

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")
minify(app=app, html=True, js=True, cssless=True)

DOWNLOAD_FOLDER = "downloads"
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# Spotify credentials
SPOTIPY_CLIENT_ID = 'your_spotify_client_id'
SPOTIPY_CLIENT_SECRET = 'your_spotify_client_secret'

# Initialize Spotify client
sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
    client_id=SPOTIPY_CLIENT_ID,
    client_secret=SPOTIPY_CLIENT_SECRET
))

# Dictionary to track file creation times and client IDs
file_tracker = {}
progress_status = {}
progress_lock = threading.Lock()

def generate_client_id():
    """Generate unique client ID"""
    return str(uuid.uuid4())

def clean_old_files():
    """Clean up files older than specified time"""
    while True:
        try:
            now = time.time()
            cleanup_threshold = 300  # 5 minutes
            
            with progress_lock:
                # Get all items in download folder
                items = os.listdir(DOWNLOAD_FOLDER)
                
                for item in items:
                    item_path = os.path.join(DOWNLOAD_FOLDER, item)
                    
                    # Skip if item is still being tracked
                    is_tracked = any(file_info['filename'] == item for file_info in file_tracker.values())
                    if is_tracked:
                        continue
                    
                    # Check item age
                    try:
                        item_age = now - os.path.getmtime(item_path)
                        if item_age > cleanup_threshold:
                            if os.path.isdir(item_path):
                                shutil.rmtree(item_path, ignore_errors=True)
                                print(f"Deleted old directory: {item}")
                            else:
                                os.remove(item_path)
                                print(f"Deleted old file: {item}")
                    except Exception as e:
                        print(f"Error deleting {item}: {e}")

        except Exception as e:
            print(f"Error in cleanup thread: {e}")
        
        time.sleep(60)  # Check every minute

def update_progress(data, client_id):
    """Update progress based on yt_dlp information."""
    if data['status'] == 'downloading':
        downloaded = data.get('downloaded_bytes', 0)
        total = data.get('total_bytes', data.get('total_bytes_estimate', 1))
        progress = (downloaded / total) * 100 if total > 0 else 0
        progress = min(progress, 100)
        
        with progress_lock:
            progress_status[client_id] = round(progress, 2)

        socketio.emit('progress_update', {'client_id': client_id, 'progress': round(progress, 2)})
        socketio.sleep(0.1)
    elif data['status'] == 'finished':
        with progress_lock:
            progress_status[client_id] = 100
        socketio.emit('progress_update', {'client_id': client_id, 'progress': 100})

def download_video(url, format_option, quality, client_id, timeout=300):
    """Download video/audio using yt_dlp with better error handling"""
    quality_map = {
        "144": "bestvideo[height<=144]+bestaudio/best",
        "240": "bestvideo[height<=240]+bestaudio/best",
        "360": "bestvideo[height<=360]+bestaudio/best",
        "480": "bestvideo[height<=480]+bestaudio/best",
        "720": "bestvideo[height<=720]+bestaudio/best",
        "1080": "bestvideo[height<=1080]+bestaudio/best",
        "1440": "bestvideo[height<=1440]+bestaudio/best",
        "2160": "bestvideo[height<=2160]+bestaudio/best",
        "4320": "bestvideo[height<=4320]+bestaudio/best",
    }
    selected_format = quality_map.get(quality, "bestvideo+bestaudio/best")

    ydl_opts = {
        'outtmpl': os.path.join(DOWNLOAD_FOLDER, '%(title)s.%(ext)s'),
        'progress_hooks': [lambda d: update_progress(d, client_id)],
        'socket_timeout': timeout,
        'retries': 3,
        'fragment_retries': 3,
        'skip_unavailable_fragments': True,
        'ignoreerrors': True
    }

    if format_option == "video":
        ydl_opts.update({
            'format': selected_format,
            'merge_output_format': 'mp4'
        })
    else:  # Audio
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'm4a',
                'preferredquality': '192'
            }]
        })

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if not info:
                raise Exception("Failed to extract video info")
                
            filename = ydl.prepare_filename(info)
            
            if format_option == "audio":
                filename = filename.rsplit('.', 1)[0] + ".m4a"

            if filename and os.path.exists(filename):
                with progress_lock:
                    progress_status[client_id] = 100
                    file_tracker[client_id] = {
                        'filename': os.path.basename(filename),
                        'created_at': time.time()
                    }
                
                socketio.emit('download_complete', {
                    'client_id': client_id, 
                    'filename': os.path.basename(filename)
                })
                return filename
            else:
                raise Exception("File not found after download")
    except Exception as e:
        print(f"Error during download: {e}")
        with progress_lock:
            progress_status[client_id] = -1
        socketio.emit('download_failed', {'client_id': client_id})
        return None

def get_spotify_playlist_tracks(playlist_url):
    """Get all tracks from a Spotify playlist"""
    try:
        playlist_id = re.search(r'playlist/([a-zA-Z0-9]+)', playlist_url).group(1)
        results = sp.playlist_tracks(playlist_id)
        tracks = results['items']
        
        while results['next']:
            results = sp.next(results)
            tracks.extend(results['items'])
        
        track_info = []
        for item in tracks:
            track = item['track']
            if track:  # Skip None tracks
                artists = ", ".join([artist['name'] for artist in track['artists']])
                track_info.append(f"{artists} - {track['name']}")
        
        return track_info
    except Exception as e:
        print(f"Error getting Spotify playlist: {e}")
        return []

def get_youtube_music_playlist(url):
    """Get all videos from a YouTube Music playlist"""
    ydl_opts = {
        'extract_flat': True,
        'quiet': True,
        'ignoreerrors': True
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return []
                
            if 'entries' in info:
                return [entry['url'] for entry in info['entries'] if entry]
        return []
    except Exception as e:
        print(f"Error getting YouTube Music playlist: {e}")
        return []

def create_zip_file(filenames, zip_filename):
    """Create a zip file containing all the downloaded files"""
    zip_path = os.path.join(DOWNLOAD_FOLDER, zip_filename)
    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for file in filenames:
                file_path = os.path.join(DOWNLOAD_FOLDER, file)
                if os.path.exists(file_path):
                    zipf.write(file_path, os.path.basename(file_path))
        return zip_path
    except Exception as e:
        print(f"Error creating zip file: {e}")
        return None

def download_playlist(url, format_option, quality, client_id, service):
    """Download all tracks from a playlist and create a zip file"""
    playlist_dir = os.path.join(DOWNLOAD_FOLDER, f"playlist_{client_id}")
    os.makedirs(playlist_dir, exist_ok=True)
    
    try:
        downloaded_files = []
        
        if service == "spotify":
            tracks = get_spotify_playlist_tracks(url)
            if not tracks:
                raise Exception("No tracks found in Spotify playlist")
                
            total_tracks = len(tracks)
            for i, track in enumerate(tracks):
                yt_search_url = f"ytsearch:{track}"
                filename = download_video(yt_search_url, format_option, quality, f"{client_id}_{i}")
                if filename:
                    downloaded_files.append(os.path.basename(filename))
                
                # Update progress
                socketio.emit('playlist_progress', {
                    'client_id': client_id,
                    'progress': round((i + 1) / total_tracks * 100, 2),
                    'current': i + 1,
                    'total': total_tracks,
                    'stage': 'downloading'  # Tambah stage untuk membedakan proses
                })
                
        elif service == "youtube_music":
            video_urls = get_youtube_music_playlist(url)
            if not video_urls:
                raise Exception("No videos found in YouTube Music playlist")
                
            total_tracks = len(video_urls)
            for i, video_url in enumerate(video_urls):
                filename = download_video(video_url, format_option, quality, f"{client_id}_{i}")
                if filename:
                    downloaded_files.append(os.path.basename(filename))
                
                # Update progress
                socketio.emit('playlist_progress', {
                    'client_id': client_id,
                    'progress': round((i + 1) / total_tracks * 100, 2),
                    'current': i + 1,
                    'total': total_tracks,
                    'stage': 'downloading'
                })
        
        # Filter files yang berhasil didownload
        downloaded_files = [f for f in downloaded_files if f]
        if not downloaded_files:
            raise Exception("No files were successfully downloaded")
        
        # Kirim notifikasi bahwa download selesai, mulai proses zip
        socketio.emit('playlist_progress', {
            'client_id': client_id,
            'progress': 100,
            'stage': 'zipping',
            'message': 'Membuat file ZIP...'
        })
        
        # Buat ZIP file
        playlist_name = f"playlist_{client_id}.zip"
        zip_path = create_zip_file(downloaded_files, playlist_name)
        if not zip_path or not os.path.exists(zip_path):
            raise Exception("Failed to create zip file")
        
        # Track the zip file
        with progress_lock:
            file_tracker[client_id] = {
                'filename': playlist_name,
                'created_at': time.time()
            }
        
        # Hapus file individual setelah zip berhasil dibuat
        for file in downloaded_files:
            try:
                os.remove(os.path.join(DOWNLOAD_FOLDER, file))
            except Exception as e:
                print(f"Error deleting file {file}: {e}")
        
        # Kirim notifikasi ke client bahwa ZIP siap
        socketio.emit('playlist_download_complete', {
            'client_id': client_id,
            'filename': playlist_name
        })
        
    except Exception as e:
        print(f"Error downloading playlist: {e}")
        socketio.emit('playlist_download_failed', {
            'client_id': client_id,
            'message': str(e)
        })
    finally:
        # Clean up the temporary directory
        try:
            shutil.rmtree(playlist_dir, ignore_errors=True)
        except Exception as e:
            print(f"Error cleaning up playlist directory: {e}")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/playlist')
def playlist():
    return render_template('playlist.html')

@app.route('/download', methods=['POST'])
def download():
    url = request.form['url']
    format_option = request.form['format']
    quality = request.form.get('quality', 'best')
    client_id = generate_client_id()
    
    thread = threading.Thread(target=download_video, args=(url, format_option, quality, client_id))
    thread.start()

    return jsonify({"status": "download started", "client_id": client_id})

@app.route('/download_playlist', methods=['POST'])
def handle_playlist_download():
    url = request.form['url']
    format_option = request.form['format']
    quality = request.form.get('quality', 'best')
    service = request.form['service']
    client_id = generate_client_id()
    
    thread = threading.Thread(
        target=download_playlist,
        args=(url, format_option, quality, client_id, service)
    )
    thread.start()

    return jsonify({
        "status": "playlist download started",
        "client_id": client_id
    })

@app.route('/get_filename', methods=['GET'])
def get_filename():
    client_id = request.args.get("client_id")
    if not client_id:
        return jsonify({"error": "Client ID is required"}), 400
    
    with progress_lock:
        file_info = file_tracker.get(client_id)
    
    if file_info:
        return jsonify({"filename": file_info['filename']})
    return jsonify({"error": "File not found"}), 404

@app.route('/download_file')
def download_file():
    filename = request.args.get('filename')
    if not filename:
        return "Filename is required", 400
    
    file_path = os.path.join(DOWNLOAD_FOLDER, filename)
    if os.path.exists(file_path):
        # Update the file's creation time in tracker
        with progress_lock:
            for client_id, file_info in file_tracker.items():
                if file_info['filename'] == filename:
                    file_tracker[client_id]['created_at'] = time.time()
                    break
        
        return send_file(file_path, as_attachment=True)
    return "File not found", 404

@app.route('/get_available_qualities', methods=['GET'])
def get_available_qualities():
    url = request.args.get('url')
    if not url:
        return jsonify({"error": "URL is required"}), 400

    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            available_qualities = []

            if 'formats' in info:
                for fmt in info['formats']:
                    if 'height' in fmt and fmt['height']:
                        available_qualities.append(str(fmt['height']))

            return jsonify({"qualities": sorted(set(available_qualities))})
    except Exception as e:
        print(f"Error fetching video qualities: {e}")
        return jsonify({"error": "Failed to fetch qualities"}), 500

if __name__ == '__main__':
    # Start cleanup thread
    threading.Thread(target=clean_old_files, daemon=True).start()
    
    # Start the application
    socketio.run(app, host='0.0.0.0', port=3200, debug=True, use_reloader=False)