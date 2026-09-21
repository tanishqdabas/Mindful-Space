# 🌿 MindfulSpace

A college-focused mental wellness web app powered by **Google Gemini AI** and **Google Calendar**.

Features an AI chat companion (Maya), mood check-ins, agentic distress detection, and live therapist appointment booking.

---

## ✨ Features

- **Maya** — AI wellness companion (CBT-grounded, streaming SSE responses via Gemini)
- **Mood Check-In** — journal entry, habit tracker, sentiment analysis, risk scoring
- **Distress Detection Engine** — keyword + sentiment analysis with crisis intervention
- **Live Appointment Booking** — real-time therapist availability via Google Calendar
- **Session Summaries** — end-of-session theme extraction
- **Therapist Dashboard** — anonymised distress signal log (`/flagged-sessions`)
- **Tone Selector** — motivational / constructive / soft / strict AI response modes

---

## 🚀 Getting Started

### 1. Clone & install

```bash
git clone https://github.com/yourusername/mindfulspace.git
cd mindfulspace
pip install -r requirements.txt
```

### 2. Set up environment variables

```bash
cp .env.example .env
# Edit .env with your real keys
```

### 3. Set up Google Calendar credentials

Follow the step-by-step instructions in `credentials.json.example`.

### 4. Run

```bash
python main.py
```

Visit `http://localhost:5000`

---

## 🔐 Environment Variables

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | ✅ | Flask session secret — generate with `python -c "import secrets; print(secrets.token_hex(32))"` |
| `GEMINI_API_KEY` | ✅ | Google Gemini API key — get at [aistudio.google.com](https://aistudio.google.com/app/apikey) |
| `GEMINI_MODEL` | Optional | Model to use (default: `gemini-1.5-flash`) |
| `GOOGLE_CALENDAR_T1`…`P3` | Optional | Therapist/supporter Google Calendar IDs |
| `CALENDLY_API_KEY` | Optional | Only needed for Calendly integration |

---

## 📁 Project Structure

```
mindfulspace/
├── main.py                  # Flask app — all routes
├── ai_engine.py             # Gemini API, Maya persona, distress detection
├── calendar_engine.py       # Google Calendar integration
├── templates/
│   └── index.html           # Single-page Jinja2 template
├── requirements.txt
├── .env.example             # Environment variable template
├── credentials.json.example # Google OAuth2 setup guide
└── .gitignore
```

---

## ⚠️ Security Notes

- **Never commit** `credentials.json`, `token.json`, or `.env` — all are gitignored
- The `/flagged-sessions` therapist dashboard must be protected by auth before production deployment
- All user identifiers in distress logs are one-way SHA-256 hashed

---

## 🛠️ Tech Stack

- **Backend**: Flask (Python)
- **AI**: Google Gemini 1.5 Flash/Pro
- **Calendar**: Google Calendar API v3
- **Auth**: Google OAuth2
- **Scheduler**: APScheduler
- **Frontend**: Vanilla JS + SSE for streaming

---

## 📋 Diagnostic Tools

- `GET /test-calendar` — verify Google Calendar connection
- `GET /flagged-sessions` — therapist distress signal dashboard

---

## 📄 License

MIT
