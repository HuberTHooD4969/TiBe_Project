# pyrefly: ignore [missing-import]
import customtkinter as ctk
from tkinter import messagebox
import os
import sys
import subprocess
import threading
import cv2 
import numpy as np
import imageio_ffmpeg

# Set theme
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

class TiBeMaster(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("TiBe - Ultra AI Video Suite")
        self.geometry("800x750")
        self.configure(fg_color="#0a0b0d") 

        # --- Header ---
        self.header_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="#14161a", height=70)
        self.header_frame.pack(fill="x", side="top")
        self.title_label = ctk.CTkLabel(self.header_frame, text="TiBe", font=("Impact", 42), text_color="#00d4ff")
        self.title_label.place(relx=0.5, rely=0.5, anchor="center")

        # --- UI Elements ---
        self.url_entry = ctk.CTkEntry(self, placeholder_text="Paste 4K/8K Video Link...", width=550, height=45, border_color="#00d4ff")
        self.url_entry.pack(pady=20)

        self.quality_var = ctk.StringVar(value="1080p")
        self.quality_btn = ctk.CTkSegmentedButton(self, values=["720p", "1080p", "2K", "4K"], variable=self.quality_var, selected_color="#00d4ff", selected_hover_color="#00aacc")
        self.quality_btn.pack(pady=5)

        self.prog_label = ctk.CTkLabel(self, text="TiBe ENGINE: READY", font=("Arial", 12, "bold"), text_color="#00d4ff")
        self.prog_label.pack(pady=5)
        
        self.progress_bar = ctk.CTkProgressBar(self, width=500, progress_color="#00d4ff")
        self.progress_bar.set(0)
        self.progress_bar.pack(pady=10)

        # Enhancement Switch
        self.sw_ultra = ctk.CTkSwitch(self, text="TiBe Ultra Enhancement (Color + Sharpness)", progress_color="#00d4ff")
        self.sw_ultra.select()
        self.sw_ultra.pack(pady=20)

        self.action_btn = ctk.CTkButton(self, text="START ULTRA ENGINE", font=("Arial", 20, "bold"), 
                                        height=65, width=350, corner_radius=32, fg_color="#00d4ff", 
                                        text_color="black", command=self.start_pipeline)
        self.action_btn.pack(pady=10)

        self.downloads_btn = ctk.CTkButton(self, text="Open Downloads", font=("Arial", 14, "bold"), 
                                        height=40, width=200, corner_radius=20, fg_color="#333333", 
                                        text_color="white", command=self.open_downloads)
        self.downloads_btn.pack(pady=10)

    def open_downloads(self):
        downloads_path = os.path.abspath("Downloads")
        if not os.path.exists(downloads_path):
            os.makedirs(downloads_path)
        if os.name == 'nt':
            os.startfile(downloads_path)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', downloads_path])
        else:
            subprocess.Popen(['xdg-open', downloads_path])

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
            
            if not os.path.exists("Downloads"): os.makedirs("Downloads")
            
            quality = self.quality_var.get()
            height_map = {"720p": 720, "1080p": 1080, "2K": 1440, "4K": 2160}
            target_height = height_map.get(quality, 1080)
            
            ydl_opts = {
                'format': f'bestvideo[height<={target_height}][ext=mp4]+bestaudio[ext=m4a]/best[height<={target_height}][ext=mp4]/best',
                'outtmpl': 'Downloads/raw_video.%(ext)s',
                'merge_output_format': 'mp4',
                'noplaylist': True,
                'overwrites': True,
                'ffmpeg_location': imageio_ffmpeg.get_ffmpeg_exe()
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            if self.sw_ultra.get():
                self.after(0, lambda: self.prog_label.configure(text="ENGINE STATUS: APPLYING ULTRA FILTERS...", text_color="yellow"))
                self.after(0, lambda: self.progress_bar.set(0.5))
                self.ultra_enhance("Downloads/raw_video.mp4")
            
            self.after(0, lambda: self.progress_bar.set(1.0))
            self.after(0, lambda: self.prog_label.configure(text="SUCCESS! ULTRA VIDEO CREATED", text_color="#00ff88"))
            self.after(0, lambda: messagebox.showinfo("Success", "Video download and processing completed successfully!"))
            
        except Exception as e:
            self.after(0, lambda: self.prog_label.configure(text=f"ENGINE STATUS: FAILED", text_color="red"))
            print(f"Error details: {e}")
            
        self.after(0, lambda: self.action_btn.configure(state="normal"))

    def ultra_enhance(self, video_path):
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise Exception("Failed to open raw video file")
            
        w, h = int(cap.get(3)), int(cap.get(4))
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 0: total_frames = 1
        
        # Output as .mp4
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter('Downloads/TiBe_Ultra_4K.mp4', fourcc, fps, (w, h))

        frame_idx = 0
        try:
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret: break

                # 1. Denoise
                frame = cv2.fastNlMeansDenoisingColored(frame, None, 10, 10, 7, 21)

                # 2. Detail Enhance
                frame = cv2.detailEnhance(frame, sigma_s=10, sigma_r=0.15)

                # 3. Color Correction
                lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
                l, a, b = cv2.split(lab)
                l = cv2.equalizeHist(l)
                frame = cv2.merge((l, a, b))
                frame = cv2.cvtColor(frame, cv2.COLOR_LAB2BGR)
                
                out.write(frame)
                
                frame_idx += 1
                if frame_idx % 5 == 0:
                    progress = 0.5 + (0.5 * (frame_idx / total_frames))
                    self.after(0, lambda p=progress: self.progress_bar.set(p))
        finally:
            cap.release()
            out.release()
            
            # Clean up the raw file only if the new one exists
            if os.path.exists('Downloads/TiBe_Ultra_4K.mp4') and os.path.exists(video_path):
                try:
                    os.remove(video_path)
                except Exception:
                    pass

if __name__ == "__main__":
    app = TiBeMaster()
    app.mainloop() # THIS IS CRITICAL: Keeps the window open
