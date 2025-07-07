# 🎵 YouTube & Playlist Downloader

Website sederhana untuk mengunduh video dari **YouTube** dengan berbagai resolusi hingga **8K**, serta mendukung pengunduhan playlist dari **YouTube Music** dan **Spotify** dalam format audio.

Dibangun menggunakan:
- 🖥️ **Frontend**: HTML + TailwindCSS
- 🐍 **Backend**: Python (Flask)

---

## 📸 Tampilan Aplikasi

### 🎬 Downloader Video YouTube (YouTubeDL)
![Tampilan YouTubeDL](https://i.ibb.co/4wws5rrS/Screenshot-from-2025-07-07-14-47-55.png)

### 🎧 Downloader Playlist (PlaylistDL)
![Tampilan PlaylistDL](https://i.ibb.co/xS8Z7t0P/Screenshot-from-2025-07-07-14-53-37.png)

---

## 🔧 Fitur Utama

### 🔻 YouTube Video Downloader
- Tempelkan URL video YouTube.
- Gambar thumbnail otomatis muncul.
- Pilih kualitas video dari: 27p, 45p, 90p, 144p, 240p, 360p, 480p, 720p, 1080p, 1440p (2K), 2160p (4K), hingga **4320p (8K)** jika tersedia.
- Bisa memilih **format video** atau **hanya audio**.

### 🎵 Playlist Downloader
- Mendukung playlist dari **YouTube Music**.
- Bisa unduh seluruh playlist dalam format **audio saja**.
- Hasil unduhan dikompres dalam bentuk **.zip**.

---

## ⚙️ Cara Menjalankan

```bash
git clone https://github.com/SakumDisiniPa/yt-download-python
cd nama-repo-kamu
pip install -r requirements.txt
python app.py
````

Lalu buka `http://localhost:3200` di browser kamu.

---

## ⚠️ Catatan Penting (Spotify)

> Jika ingin menggunakan fitur **Spotify Playlist Downloader**, kamu **wajib memiliki API Key Spotify** sendiri.
> Daftar gratis di [Spotify Developer Dashboard](https://developer.spotify.com/dashboard/applications)

---

## 📄 Lisensi

MIT © 2025 Sakum Tala
