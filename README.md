# TiBe - Ultra AI Video Suite 🎥✨

TiBe is a powerful desktop application that allows you to easily download high-quality videos (up to 4K!) and optionally enhance them using an "Ultra Enhancement" engine. Built with a sleek, modern, dark-themed UI, TiBe combines downloading power with computer vision enhancements to deliver a premium video experience.

## Features 🚀

- **High-Quality Video Downloading:** Download videos directly from links in 720p, 1080p, 2K, or stunning 4K resolutions.
- **TiBe Ultra Enhancement:** Toggle the ultra-enhancement engine to automatically apply AI-driven visual improvements to your downloaded videos:
  - **Denoising:** Cleans up visual noise for a smoother image.
  - **Detail Enhancement:** Sharpens edges to make the video pop.
  - **Color Correction:** Balances and enriches the color palette.
- **Sleek Modern UI:** A beautiful, responsive interface built with CustomTkinter.
- **Downloads Management:** Instantly access and manage all your downloaded and processed videos with a single click.

## Prerequisites 🛠️

Ensure you have Python 3.8 or higher installed on your system. You will also need the following Python libraries:

```bash
pip install customtkinter opencv-python numpy yt-dlp
```

## Installation & Usage 📥

1. **Clone or Download the Repository:**
   Download the `tibe.py` file to your local machine.
   
2. **Run the Application:**
   Navigate to the directory containing `tibe.py` in your terminal and run:
   ```bash
   python tibe.py
   ```

3. **How to Use:**
   - **Paste Link:** Paste a valid video link (e.g., from YouTube) into the input field.
   - **Select Quality:** Choose your desired video resolution (720p, 1080p, 2K, 4K).
   - **Toggle Enhancements:** Keep the "TiBe Ultra Enhancement" switch on to process the video, or turn it off to simply download the raw file.
   - **Start:** Click "START ULTRA ENGINE" and watch the magic happen!
   - **Open Downloads:** Once completed, click "Open Downloads" to find your raw and enhanced videos.

## Important Note on Mobile Packaging 📱

TiBe is currently a **Desktop Application**. It relies on `CustomTkinter` and `OpenCV`, which require desktop windowing systems and significant computing power. 

Because of this architecture, **TiBe cannot be directly packaged into an Android (.apk) or iOS (.ipa) mobile application** without completely rewriting the UI layer (using a framework like React Native or Kivy) and likely moving the heavy `OpenCV` processing to a cloud backend.

For desktop distribution, it is highly recommended to package this application as a `.exe` using `PyInstaller`.

## Roadmap 🗺️

- [x] Add resolution selection (720p, 1080p, 2K, 4K)
- [x] Add direct Downloads folder access
- [ ] Add support for custom output directories
- [ ] Implement multi-threading for faster frame processing
- [ ] Explore cloud APIs for mobile app support

## License 📄

This project is licensed under the MIT License - see the LICENSE file for details.
