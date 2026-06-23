---
title: UniDev Toolkit
emoji: 
colorFrom: blue
colorTo: purple
sdk: docker
pinned: false
license: mit
app_port: 7860
---

# UniDev Toolkit

A unified developer tool combining build automation, file conversion, and universal editing in one interface.

## Features

- **Build & Package** Generate `.dmg`, `.apk`, `.ipa`, and `.msix` from GitHub, GitLab, or uploaded project archives
- **File Converter** Bidirectional conversion with automatic type detection (code, images, audio, video, documents)
- **Universal Editor** Syntax-aware Monaco editor with format switching
- **Shared Terminal** xterm.js terminal across all tabs with live build output

## Privacy

No accounts, no cookies, no tracking, no ads, completely free.

## Local Development

```bash
# Backend
cd backend && pip install -r requirements.txt
uvicorn app:app --reload --port 7860

# Frontend (separate terminal)
cd frontend && npm install && npm run dev
```

Or use `./start.sh` to run both (builds frontend first).

## License

MIT
