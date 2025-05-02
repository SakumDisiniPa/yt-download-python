from flask import Flask, render_template, request, send_file, jsonify
from flask_socketio import SocketIO
from flask_minify import minify
import yt_dlp
import os
import threading
import time
import uuid
from datetime import datetime, timedelta

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")
minify(app=app, html=True, js=True, cssless=True)

DOWNLOAD_FOLDER = "downloads"
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# Dictionary to track file creation times and client IDs
file_tracker = {}
progress_status = {}
progress_lock = threading.Lock()

def generate_client_id():
    """Generate unique client ID"""
    return str(uuid.uuid4())

def clean_old_files():
    """Clean up files older than specified time (now set to 10 seconds)"""
    while True:
        try:
            now = time.time()
            cleanup_threshold = 10  # Files older than 10 seconds will be deleted
            
            with progress_lock:
                # First get all files in download folder
                existing_files = set(os.listdir(DOWNLOAD_FOLDER))
                
                # Track files to keep (recently downloaded)
                files_to_keep = set()
                for client_id, file_info in list(file_tracker.items()):
                    filename = file_info['filename']
                    file_path = os.path.join(DOWNLOAD_FOLDER, filename)
                    
                    # If file exists and is still new, keep it
                    if filename in existing_files and (now - file_info['created_at']) <= cleanup_threshold:
                        files_to_keep.add(filename)
                    else:
                        # File is old or doesn't exist, remove it
                        if os.path.exists(file_path):
                            try:
                                os.remove(file_path)
                                print(f"Deleted old file: {filename}")
                            except Exception as e:
                                print(f"Error deleting file {filename}: {e}")
                        # Remove from tracker
                        file_tracker.pop(client_id, None)
                
                # Now check for any untracked files in download folder
                for filename in existing_files - files_to_keep:
                    file_path = os.path.join(DOWNLOAD_FOLDER, filename)
                    file_age = now - os.path.getctime(file_path)
                    if file_age > cleanup_threshold:
                        try:
                            os.remove(file_path)
                            print(f"Deleted untracked old file: {filename}")
                        except Exception as e:
                            print(f"Error deleting untracked file {filename}: {e}")

        except Exception as e:
            print(f"Error in cleanup thread: {e}")
        
        time.sleep(5)  # Check every 5 seconds

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

def download_video(url, format_option, quality, client_id):
    """Download video/audio using yt_dlp."""
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
        'progress_hooks': [lambda d: update_progress(d, client_id)]
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
            filename = ydl.prepare_filename(info)
            
            if format_option == "audio":
                filename = filename.rsplit('.', 1)[0] + ".m4a"

            if filename and os.path.exists(filename):
                with progress_lock:
                    progress_status[client_id] = 100
                    # Track the file with creation time
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
                print(f"File not found after download: {filename}")
    except Exception as e:
        print(f"Error during download: {e}")
    
    with progress_lock:
        progress_status[client_id] = -1
    socketio.emit('download_failed', {'client_id': client_id})
    return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/download', methods=['POST'])
def download():
    url = request.form['url']
    format_option = request.form['format']
    quality = request.form.get('quality', 'best')
    client_id = generate_client_id()
    
    thread = threading.Thread(target=download_video, args=(url, format_option, quality, client_id))
    thread.start()

    return jsonify({"status": "download started", "client_id": client_id})

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