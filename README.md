---
title: UniDev Toolkit
emoji: 🛠️
colorFrom: blue
colorTo: purple
sdk: docker
pinned: false
license: mit
app_port: 7860
---

# UniDev Toolkit

A unified, zero-account developer tool combining build packaging, file conversion, and universal code editing in one interface — deployable on Hugging Face Spaces with one push.

**No accounts · No login · No cookies · No tracking · No ads · Completely free**

---

## Features

### Tab 1 — Build & Package
Generate installable packages from a GitHub repo, GitLab repo, or uploaded ZIP archive.

| Target | Format | Platform |
|--------|--------|----------|
| macOS app | `.dmg` | macOS |
| Android app | `.apk` | Android |
| iOS app | `.ipa` | iOS |
| Windows app | `.msix` | Windows 10/11 |

- Auto-detects project structure (Vite, Next.js, Create React App, plain HTML, etc.)
- Finds `index.html` at any depth — not hardcoded to a fixed path
- Uses existing PWA manifest/icons when present; prompts for manual input when not
- Build logs stream live to the shared xterm.js terminal
- Private repos supported via personal access token (GitHub `ghp_…` or GitLab `glpat-…`)

> **Hugging Face note:** `hdiutil` (native DMG) requires macOS. On Linux/HF the packager produces a `.app` bundle inside a ZIP with the `.dmg` extension. Open on macOS by extracting and double-clicking the `.app`.

### Tab 2 — File Converter
Bidirectional conversion with automatic file-type detection.

- **Images:** PNG ↔ JPG · GIF · BMP · WEBP · ICO · TIFF · PPM
- **Data:** JSON ↔ YAML · XML · CSV ↔ TSV
- **Documents:** Markdown ↔ HTML · TXT ↔ MD · TXT/MD → PDF · PDF → TXT
- **Code → HTML:** syntax-highlighted HTML output via Pygments
- **Code ↔ Code:** labelled stub with original source preserved as comments
- **Audio/Video:** any ↔ any via ffmpeg (requires ffmpeg on server)
- Image preview rendered inline after conversion
- Persistent reverse-convert button — works after tab switch, works multiple times

### Tab 3 — Universal Editor
Full Monaco editor (same engine as VS Code).

- Opens any text or code file via drag-and-drop or file picker
- Binary files (PNG, PDF, WASM, etc.) detected and shown as hex preview instead of garbled text
- Language selector driven by the backend's live format registry — never a hardcoded list
- Unsaved-changes guard before format switching
- Switch Format converts content in-place (e.g. JSON → YAML while editing)
- Download / Export button saves the current content with the correct filename

### Shared xterm.js Terminal
- Persistent across all tab switches — always visible in the right panel
- Build log output from all packaging jobs streams here automatically
- Full PTY bash shell sandboxed to the workspace directory
- Credentials (HF_TOKEN, GH_TOKEN, API keys) are scrubbed from the shell environment

---

## Quick Start — Local Development

```bash
# Clone
git clone https://github.com/YOUR_USERNAME/unidev-toolkit.git
cd unidev-toolkit

# One-command start (builds frontend, installs backend, starts server)
./start.sh
```

Then open **http://localhost:7860**

### Manual setup

```bash
# Backend (terminal 1)
cd backend
pip install -r requirements.txt
uvicorn app:app --reload --port 7860

# Frontend (terminal 2)
cd frontend
npm install
npm run dev        # dev server on :5173, proxies API to :7860
```

---

## Deployment

### Option A — Hugging Face Spaces (recommended)

The repo deploys automatically via the CI/CD pipeline. See the
[Setup Guide](#setup-guide) section for one-time configuration.

### Option B — Any Docker host

```bash
docker build -t unidev-toolkit .
docker run -p 7860:7860 unidev-toolkit
```

### Option C — Manual push to HF

```bash
pip install huggingface_hub
python -c "
from huggingface_hub import HfApi
HfApi(token='YOUR_HF_TOKEN').upload_folder(
    folder_path='.',
    repo_id='YOUR_HF_USERNAME/unidev-toolkit',
    repo_type='space',
    ignore_patterns=['.git','node_modules','frontend/dist','__pycache__'],
)
"
```

---

## Setup Guide

### GitHub Repository Settings

1. **Create the repo** at github.com/new (public or private, both work)
2. Push this code:
   ```bash
   git remote add origin https://github.com/YOUR_USERNAME/unidev-toolkit.git
   git push -u origin main
   ```
3. Go to **Settings → Secrets and variables → Actions → New repository secret**:

   | Secret name | Value |
   |-------------|-------|
   | `HF_TOKEN` | Your Hugging Face token (write access) — see below |
   | `HF_SPACE` | `YOUR_HF_USERNAME/unidev-toolkit` |

4. That's it. Every push to `main` runs CI and deploys to HF automatically.

---

### Hugging Face Space Settings

1. Go to **huggingface.co** → click your avatar → **New Space**
2. Fill in:
   - **Space name:** `unidev-toolkit` (or anything you like)
   - **License:** MIT
   - **SDK:** Docker ← **important**
   - **Hardware:** CPU Basic (free) is fine
   - **Visibility:** Public or Private
3. Click **Create Space** — ignore the starter files, CI will overwrite them.
4. Get your **write token:**
   - Go to **Settings → Access Tokens → New token**
   - Name: `github-deploy`, Role: **Write**
   - Copy the token value (starts with `hf_…`)
5. Paste that token as `HF_TOKEN` in your GitHub repo secrets (step 3 above).
6. Set `HF_SPACE` to `YOUR_HF_USERNAME/unidev-toolkit`.

The Space will build and go live within ~3 minutes of your first push.

---

### GitLab Setup (alternative to GitHub)

1. Create a GitLab repo and push code normally.
2. Go to **Settings → CI/CD → Variables** and add:

   | Variable | Value | Protected | Masked |
   |----------|-------|-----------|--------|
   | `HF_TOKEN` | `hf_…` | ✓ | ✓ |
   | `HF_SPACE` | `user/unidev-toolkit` | ✓ | ✗ |

3. Pipelines run on every push to `main`/`master`.

---

## Environment Variables

The app reads these at runtime (all optional):

| Variable | Default | Purpose |
|----------|---------|---------|
| `PORT` | `7860` | Port to listen on |

The terminal shell has `HF_TOKEN`, `GH_TOKEN`, `GITLAB_TOKEN`, and any variable containing `SECRET`, `PASSWORD`, or `API_KEY` automatically removed from its environment so they cannot be accessed via the browser terminal.

---

## Project Structure

```
unidev-toolkit/
├── backend/
│   ├── app.py                        # FastAPI app, all routes
│   ├── requirements.txt
│   ├── data/
│   │   └── formats.json              # Extension catalogue (auto-updated from Wikipedia)
│   └── services/
│       ├── build_log.py              # Broadcast stream for terminal
│       ├── build_service.py          # Clone, analyse, dispatch builds
│       ├── converter.py              # All file conversion logic
│       ├── format_registry.py        # Extension → category / Monaco language
│       ├── format_scraper.py         # Fetches Wikipedia format list on startup
│       ├── project_analyzer.py       # Detect framework, PWA assets
│       ├── terminal.py               # PTY session (sandboxed)
│       └── packagers/
│           ├── common.py             # find_index_html, copy_assets helpers
│           ├── dmg.py                # macOS .dmg / .app bundle
│           ├── apk.py                # Android .apk
│           ├── ipa.py                # iOS .ipa
│           └── msix.py               # Windows .msix
├── frontend/
│   ├── package.json
│   └── src/
│       ├── App.tsx
│       ├── index.css
│       ├── main.tsx
│       ├── components/
│       │   └── Terminal.tsx          # xterm.js shared terminal
│       └── tabs/
│           ├── BuildTab.tsx
│           ├── ConverterTab.tsx      # Image preview, reverse convert
│           └── EditorTab.tsx         # Binary detection, dynamic language list
├── .github/workflows/ci.yml          # GitHub Actions — build + HF deploy
├── .gitlab-ci.yml                    # GitLab CI — build + HF deploy
├── Dockerfile                        # Multi-stage, non-root, python:3.11
├── start.sh                          # Local dev launcher
└── README.md
```

---

## License

MIT — free to use, modify, and deploy.
