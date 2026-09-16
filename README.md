<div align="center">

# 🎨 BoozStudio — R34 Poster

### A modern, AI-powered batch uploader for Rule34.xxx

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776ab?logo=python&logoColor=white)](https://www.python.org/)
[![CustomTkinter](https://img.shields.io/badge/GUI-CustomTkinter-6366F1)](https://github.com/TomSchimansky/CustomTkinter)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![100% Vibe Coded](https://img.shields.io/badge/100%25-Vibe%20Coded%20🤖-blueviolet)](https://github.com/BoozAIYaoi/r34-poster)
[![Windows](https://img.shields.io/badge/Platform-Windows-0078d7?logo=windows)](https://www.microsoft.com/windows)

*Queue up your images, auto-tag them with WD14 AI, clean & validate tags,*  
*then upload them to Rule34.xxx — all from one sleek dark UI.*

</div>

---

## ✨ Features

- **🤖 WD14 AI Auto-Tagger** — Runs SmilingWolf's `wd-v1-4-vit-tagger-v2` locally (ONNX) to generate descriptive tags automatically. GPU-accelerated if CUDA or DirectML is available.
- **🔍 Live Tag Autocomplete** — Every tag field queries the Rule34 autocomplete API in real time as you type, with color-coded results by tag type (character, copyright, artist, general).
- **✅ Tag Validator** — Checks your entire tag list against Rule34's database before upload and highlights any unknown tags.
- **🧹 Tag Cleaner** — Strips AI-generation artifacts (`score_9_up`, `masterpiece`, LoRA tokens, etc.) that have no place on a booru.
- **📦 Batch Upload** — Uploads all queued images sequentially via Playwright browser automation. Supports CAPTCHA resolution by pausing for you to solve it manually.
- **📝 Batch Edit** — Apply common tags to all cards at once, append to existing tags, or copy the first card's tags to the rest.
- **🤖/🖼️ AI Generated Toggle** — A simple checkbox to add the `ai_generated` tag. Works for both AI and human-made artwork.
- **💾 Persistent Config** — Saves your settings automatically. No manual config editing needed.
- **⌨️ Keyboard Shortcuts** — `Ctrl+O` to load images, `Ctrl+S` to save config.
- **🌑 Modern Dark UI** — Built with CustomTkinter in a Cyber/Discord-inspired dark palette.

---

## 🤖 100% Vibe-Coded

> This entire project was built through AI-assisted development — every line of code, every bug fix, every feature idea was shaped through an interactive AI coding session.
> No traditional coding tutorials, no StackOverflow — just vibes. 🎵

---

## 📋 Requirements

- **Windows** (tested on Windows 10/11)
- **Python 3.10+** ([download here](https://www.python.org/downloads/) — check "Add Python to PATH" ✅)
- Internet connection
- ~700 MB disk space for the WD14 model (downloaded automatically on first use, optional)

---

## 🚀 Installation & Launch

**Just double-click `RUN.bat`** — that's it.

The script will automatically:
1. ✅ Check if Python is installed (and tell you if it's not)
2. 📦 Install all required packages
3. 🌐 Set up the Chromium browser for uploads
4. 🚀 Launch the application

> On the **very first launch**, it may take a few minutes to download packages.  
> After that, it launches instantly.

---

## ⚙️ Configuration

No manual configuration needed! Settings are saved automatically when you close the app.

Everything is configurable from the sidebar:
- **Username & Password** — Your Rule34.xxx account credentials
- **Artist** — Your artist name (the `_(artist)` suffix is added automatically)
- **Global Tags** — Tags applied to every image (default: `rating:explicit`)
- **🤖 AI Generated Content** — Toggle whether to add the `ai_generated` tag
- **Global Source URL** — Source link applied to all images (can be overridden per image)
- **Anti-ban Delay** — Wait time between uploads (3–30 seconds)
- **WD14 Threshold** — AI tagger confidence level (lower = more tags)

> Your config is saved to `config.json` locally and is **never committed to Git**.

---

## 🗺️ Usage Guide

The app follows a simple **5-step workflow**, numbered in the sidebar:

### ① Load Images  `Ctrl+O`
Click **Load Images** to open a file picker. Supports PNG, JPG, JPEG, and WebP. Each image gets its own card with tag fields.

### ② AI Auto-Tag (WD14)  *(optional)*
Click **AI Auto-Tag** to automatically generate descriptive tags using the WD14 ONNX tagger.

> ⚠️ **First run:** The model (~680 MB) downloads automatically from HuggingFace and is cached. Subsequent runs are instant.  
> This step is **optional** — you can fill in tags manually instead.

### ③ Clean Tags
Strips junk tags automatically: AI quality scores (`score_9_up`, `masterpiece`, etc.), LoRA tokens, duplicates, and normalizes formatting.

### ④ Validate on Rule34
Checks every tag against the Rule34 autocomplete API. Unknown tags show in **amber**. You can ignore these (some valid tags don't appear in autocomplete) or fix them.

### ⑤ Start Upload
Opens a Chromium browser window and uploads all images:
1. Your credentials are pre-filled on the login page
2. **Solve any CAPTCHA manually** when prompted
3. For each image, the app fills in the file, tags, source, and rating
4. **Solve the upload CAPTCHA** and click Upload — the app detects it and moves to the next image
5. An anti-ban delay is applied between each upload

---

## 🏷️ Tag Autocomplete

Both the **Character & Series** and **Descriptive Tags** fields have live Rule34 autocomplete:

| Symbol | Color | Type |
|--------|-------|------|
| `○` | Blue | General |
| `◆` | Green | Character |
| `◇` | Purple | Copyright / Series |
| `★` | Red | Artist |

- Type at least **2 characters** to trigger suggestions
- **Arrow keys** to navigate, **Enter** or **click** to select
- **Escape** to dismiss

---

## 🛠️ Troubleshooting

**"Python was not found"**
> Install Python 3.10+ from [python.org](https://www.python.org/downloads/) and check ✅ **"Add Python to PATH"** during setup. Then run `RUN.bat` again.

**WD14 downloads every time**
> The model is cached in `~/.cache/huggingface/hub`. If it keeps re-downloading, check your disk space.

**Tags are off-topic after auto-tagging**
> This was a known bug in v1/v2 (CSV index mismatch). It is fixed in v3. Make sure you're running the latest version.

**Upload fails / stuck waiting**
> Rule34 shows a CAPTCHA on every upload. The tool waits up to 1 hour per image for you to solve it — no way around it.

**The browser window doesn't open**
> Run `RUN.bat` once more — it will re-install the Playwright browser automatically.

---

## 📁 Project Structure

```
r34-poster/
├── RUN.bat               # ← Start here! One-click launcher
├── app.py                # Main application
├── requirements.txt      # Python dependencies
├── config.example.json   # Config reference (auto-created as config.json)
├── .gitignore
└── README.md
```

Files created automatically (gitignored):
```
├── config.json           # Your settings & credentials (never committed)
└── browser_data/         # Browser session (keeps you logged in)
```

---

## ⚖️ Disclaimer

- This tool is provided **as-is** for personal use.
- You are responsible for ensuring uploaded content complies with Rule34.xxx's Terms of Service.
- This project is not affiliated with Rule34.xxx.

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

<div align="center">

Made with 🤖 vibes and ☕ caffeine  
**BoozStudio**

</div>
