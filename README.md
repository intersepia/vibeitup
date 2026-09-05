# VibeItUp — Futuristic Dashboard

Ein futuristisches Dark-Glass Dashboard mit **Vue 3** und **Python 3 FastAPI**.

## Architektur

- **Frontend:** Vue 3 (via CDN), Tailwind CSS, Glassmorphism-Design, Neon-Akzente
- **Backend:** FastAPI (Python 3), REST-API, Demo-Endpunkte

## Start

### Backend (Port 8000)
```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### Frontend (Port 3000)
```bash
cd frontend
python3 -m http.server 3000
```

Öffne `http://localhost:3000` — das Frontend lädt Daten von `http://localhost:8000/api/`.

## Features

- Futuristisches Dark-Glass Design
- Live-Metriken mit Sparkline-Charts
- Responsive Widget-Grid
- Interaktive Hover-Effekte und Animationen
- FastAPI REST-API mit CORS
