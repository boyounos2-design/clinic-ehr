# Clinic EHR

Patient-records app for an orthopedic clinic (Arabic / English, RTL). FastAPI + SQLite, no build step.

**Modules:** patient demographics · clinical history & visits · file upload with OCR · prescriptions / follow-ups / reminders · global search over every field (Arabic-normalized) · **import a patient from a paper sheet** (reader fills the form; the doctor reviews before saving) · roles (admin / doctor / nurse / receptionist) · audit log.

## Run locally
- **Windows:** unzip, double-click `start.bat` (needs Python 3.11+). See `README.txt`.
- **Any OS:** `pip install -r requirements.txt && uvicorn main:app --app-dir app` → http://localhost:8000
  (demo users `admin / doctor / nurse / reception` are created on first run; **local testing only**).

## Paper-sheet readers
| Reader | Setup | Notes |
|---|---|---|
| On-server Tesseract | installed in the Docker image (Arabic + English) | printed text only; images stay on your server |
| OCR.Space | admin → Settings → key | trial reader; sheet images leave your server |
| Anthropic (Claude vision) | `ANTHROPIC_API_KEY` or admin → Settings | reads handwriting into fields; sheet images are sent to Anthropic |

Automatic reading can be wrong. The UI marks low-confidence fields and nothing is saved until the doctor presses Save.

## Deploy on a paid server (Docker + HTTPS)
1. A small Linux VPS with Docker and Docker Compose; a domain whose DNS A-record points at it; ports 80/443 open.
2. `git clone <this repo> && cd <repo> && cp .env.example .env` and edit `.env` (`DOMAIN`, a strong `EHR_ADMIN_PASSWORD`, optional API keys).
3. `docker compose up -d --build` → open `https://<DOMAIN>`, sign in as `admin`, then **Account** → add the doctor / nurse / reception users.
4. **Production mode** (`EHR_ENV=production`, set by the image): no demo users, the API docs are disabled, the app refuses to start without `EHR_ADMIN_PASSWORD` on first run.

### Before real patient data
- Back up the `ehr_data` volume (database, uploaded files, secret key) regularly and test a restore.
- Use disk encryption and keep the server patched; restrict SSH (keys only).
- This code has **not** had an independent security review. Have one done, and check your local medical-data / privacy regulations and the terms of any external reading service before using real data.
- SQLite with one worker suits a single clinic. For many concurrent users or multiple servers the storage layer needs a client-server database.

## Tests
`python test_intake.py`, and with the server running: `python smoke_test.py`, `python intake_e2e_test.py`.
