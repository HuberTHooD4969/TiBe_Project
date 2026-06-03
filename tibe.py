# pyrefly: ignore [missing-import]
import customtkinter as ctk
from tkinter import messagebox, filedialog
import os
import sys
import subprocess
import threading
import cv2
import numpy as np
import imageio_ffmpeg
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

MAX_FRAME_WORKERS = os.cpu_count() or 4

class TiBeMaster(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("TiBe - Ultra AI Video Suite")
        self.geometry("850x780")
        self.configure(fg_color="#0a0b0d")

        self.output_dir = os.path.abspath("Downloads")
        os.makedirs(self.output_dir, exist_ok=True)

        self.header_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="#14161a", height=70)
        self.header_frame.pack(fill="x", side="top")
        self.title_label = ctk.CTkLabel(self.header_frame, text="TiBe", font=("Impact", 42), text_color="#00d4ff")
        self.title_label.place(relx=0.5, rely=0.5, anchor="center")

        self.url_entry = ctk.CTkEntry(self, placeholder_text="Paste 4K/8K Video Link...", width=550, height=45, border_color="#00d4ff")
        self.url_entry.pack(pady=(20, 5))

        self.quality_var = ctk.StringVar(value="1080p")
        self.quality_btn = ctk.CTkSegmentedButton(self, values=["720p", "1080p", "2K", "4K"], variable=self.quality_var, selected_color="#00d4ff", selected_hover_color="#00aacc")
        self.quality_btn.pack(pady=5)

        self.output_dir_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.output_dir_frame.pack(pady=10, fill="x", padx=80)
        self.output_dir_label = ctk.CTkLabel(self.output_dir_frame, text=f"Output: {self.output_dir}", font=("Arial", 11), text_color="#8b92a5")
        self.output_dir_label.pack(side="left", padx=5)
        self.browse_btn = ctk.CTkButton(self.output_dir_frame, text="Browse", width=80, height=28, font=("Arial", 11), command=self.browse_output_dir)
        self.browse_btn.pack(side="right")

        self.prog_label = ctk.CTkLabel(self, text="TiBe ENGINE: READY", font=("Arial", 12, "bold"), text_color="#00d4ff")
        self.prog_label.pack(pady=5)

        self.progress_bar = ctk.CTkProgressBar(self, width=500, progress_color="#00d4ff")
        self.progress_bar.set(0)
        self.progress_bar.pack(pady=10)

        self.sw_ultra = ctk.CTkSwitch(self, text="TiBe Ultra Enhancement (Multi-Threaded)", progress_color="#00d4ff")
        self.sw_ultra.select()
        self.sw_ultra.pack(pady=10)

        self.action_btn = ctk.CTkButton(self, text="START ULTRA ENGINE", font=("Arial", 20, "bold"),
                                        height=65, width=350, corner_radius=32, fg_color="#00d4ff",
                                        text_color="black", command=self.start_pipeline)
        self.action_btn.pack(pady=10)

        self.downloads_btn = ctk.CTkButton(self, text="Open Downloads", font=("Arial", 14, "bold"),
                                        height=40, width=200, corner_radius=20, fg_color="#333333",
                                        text_color="white", command=self.open_downloads)
        self.downloads_btn.pack(pady=5)

    def browse_output_dir(self):
        path = filedialog.askdirectory(initialdir=self.output_dir, title="Select Output Directory")
        if path:
            self.output_dir = path
            self.output_dir_label.configure(text=f"Output: {path}")

    def open_downloads(self):
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
        if os.name == 'nt':
            os.startfile(self.output_dir)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', self.output_dir])
        else:
            subprocess.Popen(['xdg-open', self.output_dir])

    def start_pipeline(self):
        url = self.url_entry.get()
        if not url:
            self.prog_label.configure(text="ERROR: PASTE A LINK FIRST", text_color="red")
            return

        if yt_dlp is None:
            self.prog_label.configure(text="ERROR: yt-dlp NOT INSTALLED", text_color="red")
            return

        self.action_btn.configure(state="disabled")
        threading.Thread(target=self.run_engine, args=(url,), daemon=True).start()

    def run_engine(self, url):
        try:
            self.after(0, lambda: self.prog_label.configure(text="ENGINE STATUS: DOWNLOADING...", text_color="#00d4ff"))
            self.after(0, lambda: self.progress_bar.set(0.2))

            os.makedirs(self.output_dir, exist_ok=True)

            quality = self.quality_var.get()
            height_map = {"720p": 720, "1080p": 1080, "2K": 1440, "4K": 2160}
            target_height = height_map.get(quality, 1080)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            raw_path = os.path.join(self.output_dir, f"raw_{timestamp}.mp4")
            final_path = os.path.join(self.output_dir, f"TiBe_Ultra_{quality}_{timestamp}.mp4")

            ydl_opts = {
                'format': f'bestvideo[height<={target_height}][ext=mp4]+bestaudio[ext=m4a]/best[height<={target_height}][ext=mp4]/best',
                'outtmpl': raw_path,
                'merge_output_format': 'mp4',
                'noplaylist': True,
                'overwrites': True,
                'ffmpeg_location': imageio_ffmpeg.get_ffmpeg_exe()
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            if self.sw_ultra.get():
                self.after(0, lambda: self.prog_label.configure(text="ENGINE STATUS: APPLYING ULTRA FILTERS (MULTI-THREADED)...", text_color="yellow"))
                self.after(0, lambda: self.progress_bar.set(0.5))
                self.ultra_enhance_parallel(raw_path, final_path)
            else:
                if os.path.exists(raw_path):
                    os.rename(raw_path, final_path)

            self.after(0, lambda: self.progress_bar.set(1.0))
            self.after(0, lambda: self.prog_label.configure(text="SUCCESS! ULTRA VIDEO CREATED", text_color="#00ff88"))
            self.after(0, lambda: messagebox.showinfo("Success", f"Video saved to:\n{final_path}"))

        except Exception as e:
            self.after(0, lambda: self.prog_label.configure(text="ENGINE STATUS: FAILED", text_color="red"))
            print(f"Error details: {e}")

        self.after(0, lambda: self.action_btn.configure(state="normal"))

    def ultra_enhance_parallel(self, video_path, output_path):
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise Exception("Failed to open raw video file")

        w, h = int(cap.get(3)), int(cap.get(4))
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 0:
            total_frames = 1

        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(output_path, fourcc, fps, (w, h))

        def process_frame(frame_data):
            idx, frame = frame_data
            frame = cv2.fastNlMeansDenoisingColored(frame, None, 10, 10, 7, 21)
            frame = cv2.detailEnhance(frame, sigma_s=10, sigma_r=0.15)
            lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            l = cv2.equalizeHist(l)
            frame = cv2.merge((l, a, b))
            frame = cv2.cvtColor(frame, cv2.COLOR_LAB2BGR)
            return (idx, frame)

        frames = []
        frame_idx = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            frames.append((frame_idx, frame))
            frame_idx += 1
        cap.release()

        total = len(frames)
        processed = [None] * total
        batch_size = max(1, total // (MAX_FRAME_WORKERS * 4))

        with ThreadPoolExecutor(max_workers=MAX_FRAME_WORKERS) as executor:
            for i in range(0, total, batch_size):
                batch = frames[i:i + batch_size]
                futures = {executor.submit(process_frame, f): f[0] for f in batch}
                for future in as_completed(futures):
                    idx, result = future.result()
                    processed[idx] = result
                progress = 0.5 + (0.5 * min(i + batch_size, total) / total)
                self.after(0, lambda p=progress: self.progress_bar.set(p))

        for frame_data in processed:
            out.write(frame_data)
        out.release()

        if os.path.exists(video_path):
            try:
                os.remove(video_path)
            except Exception:
                pass

if __name__ == "__main__":
    app = TiBeMaster()
    app.mainloop()
