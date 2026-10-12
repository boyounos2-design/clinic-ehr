"""Clinic EHR — local edition (FastAPI + SQLite, runs on a single PC; only Python is required).

Data lives in ./data/ehr.db and ./data/files/.  Back up the whole ./data folder.
"""
import hashlib
import logging
import os
import re
import secrets
import sqlite3
import threading
import unicodedata
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Optional

import sys
import tempfile
from contextlib import contextmanager
from urllib.parse import quote

import bcrypt
import jwt
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent))      # lets "import intake" work however the app is launched
import intake  # noqa: E402
import ocr  # noqa: E402

USE_PG = bool(os.environ.get("DATABASE_URL"))               # PostgreSQL mode (hosted / serverless); otherwise local SQLite

log = logging.getLogger("ehr")
ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("EHR_DATA_DIR", ROOT / "data"))
DB = DATA / "ehr.db"
FILES = DATA / "files"
MAX_UPLOAD = 25 * 1024 * 1024
TOKEN_HOURS = 10
ALLOWED_MIME = {"application/pdf", "image/png", "image/jpeg", "image/tiff", "image/bmp", "image/webp", "application/dicom"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return str(uuid.uuid4())


def jwt_secret() -> str:
    if os.environ.get("EHR_JWT_SECRET"):
        return os.environ["EHR_JWT_SECRET"]
    if USE_PG:
        raise RuntimeError("Hosted mode: set EHR_JWT_SECRET (a long random string) so every server instance signs tokens the same way.")
    f = DATA / "secret.key"                                  # generated once, per installation
    if not f.exists():
        DATA.mkdir(parents=True, exist_ok=True)
        f.write_text(secrets.token_hex(32))
    return f.read_text().strip()


from intake import norm_text  # noqa: E402  (shared with the sheet parser)


# ───────────────────────── database ─────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
  full_name TEXT NOT NULL, role TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS patients(id TEXT PRIMARY KEY, mrn INTEGER UNIQUE NOT NULL, full_name TEXT NOT NULL, norm_name TEXT,
  date_of_birth TEXT, dob_approx INTEGER NOT NULL DEFAULT 0, phone TEXT, phone_digits TEXT, address TEXT, gender TEXT NOT NULL DEFAULT 'unknown', national_id TEXT,
  created_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT);
CREATE TABLE IF NOT EXISTS patient_history(id TEXT PRIMARY KEY, patient_id TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'medical',
  description TEXT NOT NULL, since_date TEXT, created_by TEXT, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_hist_p ON patient_history(patient_id);
CREATE TABLE IF NOT EXISTS visits(id TEXT PRIMARY KEY, patient_id TEXT NOT NULL, visit_date TEXT NOT NULL, chief_complaint TEXT,
  symptoms TEXT, examination TEXT, diagnosis TEXT, icd10_code TEXT, management_plan TEXT, physician_notes TEXT, doctor_id TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT);
CREATE INDEX IF NOT EXISTS ix_visits_p ON visits(patient_id, visit_date);
CREATE TABLE IF NOT EXISTS prescriptions(id TEXT PRIMARY KEY, visit_id TEXT NOT NULL, drug_name TEXT NOT NULL, dose TEXT, route TEXT,
  frequency TEXT, duration TEXT, instructions TEXT);
CREATE INDEX IF NOT EXISTS ix_rx_v ON prescriptions(visit_id);
CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, patient_id TEXT NOT NULL, visit_id TEXT, category TEXT NOT NULL DEFAULT 'other',
  original_name TEXT NOT NULL, mime_type TEXT NOT NULL, size_bytes INTEGER NOT NULL, storage_key TEXT NOT NULL, sha256 TEXT NOT NULL,
  ocr_status TEXT NOT NULL DEFAULT 'pending', ocr_text TEXT, ocr_lang TEXT, ocr_error TEXT, uploaded_by TEXT,
  uploaded_at TEXT NOT NULL, deleted_at TEXT);
CREATE INDEX IF NOT EXISTS ix_docs_p ON documents(patient_id);
CREATE TABLE IF NOT EXISTS follow_ups(id TEXT PRIMARY KEY, patient_id TEXT NOT NULL, visit_id TEXT, due_date TEXT NOT NULL, reason TEXT,
  status TEXT NOT NULL DEFAULT 'scheduled', remind_at TEXT, reminded_at TEXT, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_fu_due ON follow_ups(due_date);
CREATE TABLE IF NOT EXISTS search_index(id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id TEXT NOT NULL, source_type TEXT NOT NULL,
  source_id TEXT NOT NULL, title TEXT, norm TEXT, event_date TEXT, UNIQUE(source_type, source_id));
CREATE INDEX IF NOT EXISTS ix_si_p ON search_index(patient_id);
CREATE TABLE IF NOT EXISTS audit_log(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, action TEXT NOT NULL, entity TEXT NOT NULL,
  entity_id TEXT, detail TEXT, ip TEXT, at TEXT NOT NULL);
"""
SCHEMA_PG = SCHEMA.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY") + """
CREATE TABLE IF NOT EXISTS blobs(key TEXT PRIMARY KEY, data BYTEA NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""
_lock = threading.Lock()                       # one writer at a time keeps SQLite simple and safe
_pg = None


def _pg_conn():
    global _pg
    if _pg is None or _pg.closed:
        import psycopg
        from psycopg.rows import dict_row
        _pg = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True, row_factory=dict_row, prepare_threshold=None, connect_timeout=15)
    return _pg


def _pg_sql(sql: str) -> str:
    """The few SQLite-isms used in this file, translated for PostgreSQL."""
    return (sql.replace("%", "%%").replace("date('now','localtime')", "to_char(now() AT TIME ZONE 'Africa/Cairo','YYYY-MM-DD')")
               .replace("date('now')", "to_char(now() AT TIME ZONE 'UTC','YYYY-MM-DD')").replace("? IS NULL", "CAST(? AS TEXT) IS NULL").replace("?='all'", "CAST(? AS TEXT)='all'")
               .replace("? <> ''", "CAST(? AS TEXT) <> ''").replace("?", "%s"))


def _q_pg(sql, params, one):
    import psycopg
    for attempt in (1, 2):
        try:
            with _lock:
                sq = _pg_sql(sql)
                if isinstance(params, dict):
                    sq = re.sub(r":(\w+)", r"%(\1)s", sq)
                cur = _pg_conn().execute(sq, params)
                rows = cur.fetchall() if cur.description else None
            break
        except (psycopg.OperationalError, psycopg.InterfaceError):
            global _pg
            _pg = None                       # connection dropped (idle serverless instance): reconnect once
            if attempt == 2:
                raise
    if rows is None:
        return None
    return (rows[0] if rows else None) if one else rows


def conn():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = lambda cur, row: {d[0]: row[i] for i, d in enumerate(cur.description)}
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


def q(sql: str, params=(), one=False):
    if USE_PG:
        return _q_pg(sql, params, one)
    with _lock:
        c = conn()
        try:
            cur = c.execute(sql, params)
            rows = cur.fetchall() if cur.description else None
            c.commit()
        finally:
            c.close()
    if rows is None:
        return None
    return (rows[0] if rows else None) if one else rows


# ───────────────────────── file storage (disk locally; database in hosted mode) ─────────────────────────
def put_blob(key: str, data: bytes):
    if USE_PG:
        q("INSERT INTO blobs(key,data,created_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET data=excluded.data", (key, data, now()))
    else:
        p = FILES / key
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


def get_blob(key: str):
    if USE_PG:
        r = q("SELECT data FROM blobs WHERE key=?", (key,), one=True)
        return bytes(r["data"]) if r else None
    p = FILES / key
    return p.read_bytes() if p.exists() else None


def del_blob(key: str):
    if USE_PG:
        q("DELETE FROM blobs WHERE key=?", (key,))
    else:
        try:
            (FILES / key).unlink()
        except OSError:
            pass


@contextmanager
def blob_file(key: str):
    """A real file path for libraries that need one (OCR)."""
    if not USE_PG:
        yield FILES / key
        return
    data = get_blob(key)
    if data is None:
        raise RuntimeError("File not found")
    fd, name = tempfile.mkstemp(suffix=".bin")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        yield Path(name)
    finally:
        try:
            os.unlink(name)
        except OSError:
            pass


def kv_get(name: str):
    if USE_PG:
        r = q("SELECT value FROM settings WHERE key=?", (name,), one=True)
        return r["value"] if r else None
    f = DATA / f"{name}.txt"
    return f.read_text().strip() or None if f.exists() else None


def kv_set(name: str, value):
    if USE_PG:
        if value:
            q("INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (name, value))
        else:
            q("DELETE FROM settings WHERE key=?", (name,))
        return
    f = DATA / f"{name}.txt"
    if value:
        f.write_text(value)
    elif f.exists():
        f.unlink()


intake.kv_get = kv_get


def audit(user, action, entity, entity_id=None, detail=None, request: Request | None = None):
    import json
    q("INSERT INTO audit_log(user_id,action,entity,entity_id,detail,ip,at) VALUES (?,?,?,?,?,?,?)",
      (user["id"] if user else None, action, entity, entity_id, json.dumps(detail) if detail else None,
       request.client.host if request and request.client else None, now()))


# ───────────────────────── search index (kept in sync by the code that writes records) ─────────────────────────
def idx(patient_id, st, sid, title, body, event_date):
    q("""INSERT INTO search_index(patient_id,source_type,source_id,title,norm,event_date) VALUES (?,?,?,?,?,?)
         ON CONFLICT(source_type,source_id) DO UPDATE SET patient_id=excluded.patient_id,title=excluded.title,
         norm=excluded.norm,event_date=excluded.event_date""",
      (patient_id, st, sid, title, norm_text(f"{title or ''} {body or ''}"), event_date))


def unidx(st, sid):
    q("DELETE FROM search_index WHERE source_type=? AND source_id=?", (st, sid))


def join(*parts):
    return " ".join(str(p) for p in parts if p not in (None, ""))


def index_patient(pid):
    p = q("SELECT * FROM patients WHERE id=?", (pid,), one=True)
    if not p or p["deleted_at"]:
        return unidx("patient", pid)
    idx(pid, "patient", pid, p["full_name"], join(p["phone"], p["phone_digits"], p["address"], p["gender"], None if p["dob_approx"] else p["date_of_birth"], p["mrn"]), p["created_at"])


def index_history(hid):
    h = q("SELECT * FROM patient_history WHERE id=?", (hid,), one=True)
    if h:
        idx(h["patient_id"], "history", hid, "History: " + h["kind"], h["description"], h["created_at"])


def index_visit(vid):
    v = q("SELECT * FROM visits WHERE id=?", (vid,), one=True)
    if not v or v["deleted_at"]:
        return unidx("visit", vid)
    rx = "; ".join(join(r["drug_name"], r["dose"], r["route"], r["frequency"], r["duration"], r["instructions"])
                   for r in q("SELECT * FROM prescriptions WHERE visit_id=?", (vid,)))
    idx(v["patient_id"], "visit", vid, "Visit " + v["visit_date"][:10],
        join(v["chief_complaint"], v["symptoms"], v["examination"], v["diagnosis"], v["icd10_code"], v["management_plan"], v["physician_notes"], rx),
        v["visit_date"])


def index_document(did):
    d = q("SELECT * FROM documents WHERE id=?", (did,), one=True)
    if not d or d["deleted_at"]:
        return unidx("document", did)
    idx(d["patient_id"], "document", did, d["original_name"], join(d["category"], d["ocr_text"]), d["uploaded_at"])


def index_followup(fid):
    f = q("SELECT * FROM follow_ups WHERE id=?", (fid,), one=True)
    if f:
        idx(f["patient_id"], "followup", fid, "Follow-up " + f["due_date"], join(f["reason"], f["status"]), f["due_date"] + "T00:00:00")


# ───────────────────────── app + auth ─────────────────────────
def hash_pw(p: str) -> str:
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()


DEMO_USERS = [("admin", "Admin#12345", "System Admin", "admin"), ("doctor", "Doctor#12345", "Dr. Demo", "doctor"),
              ("nurse", "Nurse#12345", "Nurse Demo", "nurse"), ("reception", "Desk#12345", "Front Desk", "receptionist")]


def init_db():
    if USE_PG:
        if not q("SELECT to_regclass('public.users') AS t", one=True)["t"]:
            with _lock:
                c = _pg_conn()
                c.execute("SELECT pg_advisory_lock(7731)")
                try:
                    c.execute(SCHEMA_PG)
                finally:
                    c.execute("SELECT pg_advisory_unlock(7731)")
    else:
        DATA.mkdir(parents=True, exist_ok=True)
        FILES.mkdir(parents=True, exist_ok=True)
        c = conn()
        c.executescript(SCHEMA)
        if "dob_approx" not in [r["name"] for r in c.execute("PRAGMA table_info(patients)").fetchall()]:   # upgrade older databases
            c.execute("ALTER TABLE patients ADD COLUMN dob_approx INTEGER NOT NULL DEFAULT 0")
        c.commit()
        c.close()
    if os.environ.get("EHR_RESET_ADMIN") == "1" and os.environ.get("EHR_ENV") == "production":
        # Recovery: with access to the server's environment you can reset the admin password. Remove the flag afterwards.
        pw = os.environ.get("EHR_ADMIN_PASSWORD", "")
        if len(pw) < 12:
            raise RuntimeError("EHR_RESET_ADMIN needs EHR_ADMIN_PASSWORD (at least 12 characters).")
        au = os.environ.get("EHR_ADMIN_USER", "admin")
        if q("SELECT 1 FROM users WHERE username=?", (au,), one=True):
            q("UPDATE users SET password_hash=? WHERE username=?", (hash_pw(pw), au))
        else:
            q("INSERT INTO users(id,username,password_hash,full_name,role,created_at) VALUES (?,?,?,?,?,?)",
              (new_id(), au, hash_pw(pw), "Administrator", "admin", now()))
        log.warning("Admin password was reset from EHR_ADMIN_PASSWORD. Remove EHR_RESET_ADMIN now.")
    if not q("SELECT 1 FROM users LIMIT 1", one=True) and os.environ.get("EHR_ENV") == "production":
        pw = os.environ.get("EHR_ADMIN_PASSWORD", "")
        if len(pw) < 12:
            raise RuntimeError("Production mode: set EHR_ADMIN_PASSWORD (at least 12 characters) for the first start. No demo users are created.")
        q("INSERT INTO users(id,username,password_hash,full_name,role,created_at) VALUES (?,?,?,?,?,?) ON CONFLICT(username) DO NOTHING",
          (new_id(), os.environ.get("EHR_ADMIN_USER", "admin"), hash_pw(pw), "Administrator", "admin", now()))
        log.warning("Production first run: created the admin account only. Add the other users from the app.")
    elif not q("SELECT 1 FROM users LIMIT 1", one=True):
        for u, p, n, r in DEMO_USERS:
            q("INSERT INTO users(id,username,password_hash,full_name,role,created_at) VALUES (?,?,?,?,?,?)", (new_id(), u, hash_pw(p), n, r, now()))
        log.warning("First run: demo users created (admin/doctor/nurse/reception). Change their passwords before real use.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    intake_cleanup()
    if not USE_PG:                                           # hosted mode reads files inline, no background queue
        q("UPDATE documents SET ocr_status='pending' WHERE ocr_status='processing'")      # crash recovery
        pending = [r["id"] for r in q("SELECT id FROM documents WHERE ocr_status='pending' AND deleted_at IS NULL")]
        threading.Thread(target=lambda: [run_ocr(i) for i in pending], daemon=True).start()
    yield


_prod = os.environ.get("EHR_ENV") == "production"
app = FastAPI(title="Clinic EHR", version="1.0", lifespan=lifespan,
              docs_url=None if _prod else "/docs", redoc_url=None, openapi_url=None if _prod else "/openapi.json")


@app.get("/api/health")
def health():
    return {"ok": True}
SECRET = jwt_secret()


def make_token(u) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=TOKEN_HOURS)
    return jwt.encode({"sub": u["id"], "role": u["role"], "exp": exp}, SECRET, algorithm="HS256")


def current_user(request: Request):
    h = request.headers.get("authorization", "")
    tok = h[7:] if h.lower().startswith("bearer ") else request.query_params.get("token")
    if not tok:
        raise HTTPException(401, "Not authenticated")
    try:
        data = jwt.decode(tok, SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired token")
    u = q("SELECT id,username,full_name,role FROM users WHERE id=? AND is_active=1", (data["sub"],), one=True)
    if not u:
        raise HTTPException(401, "User disabled")
    return u


def roles(*allowed: str):
    def dep(u=Depends(current_user)):
        if u["role"] not in allowed:
            raise HTTPException(403, "Your role cannot do this")
        return u
    return dep


CLINICAL = Depends(roles("doctor", "nurse", "admin"))
DOCTOR = Depends(roles("doctor", "admin"))
ANY = Depends(current_user)
STAFF = Depends(roles("doctor", "nurse", "receptionist", "admin"))
ADMIN = Depends(roles("admin"))


class LoginIn(BaseModel):
    username: str
    password: str


@app.post("/api/auth/login")
def login(body: LoginIn, request: Request):
    u = q("SELECT * FROM users WHERE username=? AND is_active=1", (body.username,), one=True)
    if not (u and bcrypt.checkpw(body.password.encode(), u["password_hash"].encode())):
        audit(None, "login_failed", "user", None, {"username": body.username}, request)
        raise HTTPException(401, "Wrong username or password")
    audit(u, "login", "user", u["id"], None, request)
    return {"token": make_token(u), "user": {k: u[k] for k in ("id", "username", "full_name", "role")}}


@app.get("/api/auth/me")
def me(u=ANY):
    return u


# ───────────────────────── models ─────────────────────────
class PatientIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    date_of_birth: Optional[date] = None
    age_years: Optional[int] = Field(None, ge=0, le=120)       # used only when no date of birth is known -> stored as approximate
    phone: Optional[str] = Field(None, max_length=40)
    address: Optional[str] = None
    gender: Literal["male", "female", "other", "unknown"] = "unknown"
    national_id: Optional[str] = None


class HistoryIn(BaseModel):
    kind: Literal["medical", "surgical", "medication", "allergy", "family", "social"] = "medical"
    description: str = Field(min_length=1)
    since_date: Optional[date] = None


class RxIn(BaseModel):
    drug_name: str = Field(min_length=1)
    dose: Optional[str] = None
    route: Optional[str] = None
    frequency: Optional[str] = None
    duration: Optional[str] = None
    instructions: Optional[str] = None


class VisitIn(BaseModel):
    visit_date: Optional[datetime] = None
    chief_complaint: Optional[str] = None
    symptoms: Optional[str] = None
    examination: Optional[str] = None
    diagnosis: Optional[str] = None
    icd10_code: Optional[str] = None
    management_plan: Optional[str] = None
    physician_notes: Optional[str] = None
    prescriptions: list[RxIn] = []
    follow_up_date: Optional[date] = None
    follow_up_reason: Optional[str] = None


class FollowUpIn(BaseModel):
    due_date: date
    reason: Optional[str] = None
    visit_id: Optional[str] = None
    remind_days_before: int = 1


class FollowUpPatch(BaseModel):
    status: Optional[Literal["scheduled", "done", "missed", "cancelled"]] = None
    due_date: Optional[date] = None
    reason: Optional[str] = None


class OcrTextIn(BaseModel):
    ocr_text: str


def iso(d):
    return d.isoformat() if d else None


def with_age(p):
    p = dict(p)
    p.pop("norm_name", None)
    dob = p.get("date_of_birth")
    if dob:
        b, t = date.fromisoformat(dob), date.today()
        p["age_years"] = t.year - b.year - ((t.month, t.day) < (b.month, b.day))
    else:
        p["age_years"] = None
    return p


def get_patient_or_404(pid):
    p = q("SELECT * FROM patients WHERE id=? AND deleted_at IS NULL", (pid,), one=True)
    if not p:
        raise HTTPException(404, "Patient not found")
    return with_age(p)


# ───────────────────────── patients ─────────────────────────
@app.get("/api/patients")
def list_patients(search: str = "", limit: int = Query(50, le=200), offset: int = 0, u=ANY):
    s = search.strip()
    if not s:
        rows = q("SELECT * FROM patients WHERE deleted_at IS NULL ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset))
    else:
        digits = re.sub(r"\D", "", norm_text(s))
        rows = q("""SELECT * FROM patients WHERE deleted_at IS NULL AND (norm_name LIKE ? ESCAPE '\\'
                    OR (? <> '' AND (phone_digits LIKE ? ESCAPE '\\' OR CAST(mrn AS TEXT) = ?)))
                    ORDER BY created_at DESC LIMIT ? OFFSET ?""",
                 (f"%{like_escape(norm_text(s))}%", digits, f"%{digits}%", digits, limit, offset))
    return [with_age(r) for r in rows]


def save_patient(pid, b: PatientIn, by=None, create=False):
    d = b.model_dump()
    dob, approx = iso(d["date_of_birth"]), 0
    if not dob and d["age_years"] is not None:                 # only an age is known: store 1 Jan of the birth year, flagged approximate
        dob, approx = date(date.today().year - d["age_years"], 1, 1).isoformat(), 1
    digits = re.sub(r"\D", "", norm_text(d["phone"] or ""))
    if create:
        q("""INSERT INTO patients(id,mrn,full_name,norm_name,date_of_birth,dob_approx,phone,phone_digits,address,gender,national_id,created_by,created_at,updated_at)
             VALUES (?,(SELECT COALESCE(MAX(mrn),0)+1 FROM patients),?,?,?,?,?,?,?,?,?,?,?,?)""",
          (pid, d["full_name"], norm_text(d["full_name"]), dob, approx, d["phone"], digits, d["address"], d["gender"], d["national_id"], by, now(), now()))
    else:
        q("""UPDATE patients SET full_name=?,norm_name=?,date_of_birth=?,dob_approx=?,phone=?,phone_digits=?,address=?,gender=?,national_id=?,updated_at=? WHERE id=?""",
          (d["full_name"], norm_text(d["full_name"]), dob, approx, d["phone"], digits, d["address"], d["gender"], d["national_id"], now(), pid))
    index_patient(pid)


@app.post("/api/patients", status_code=201)
def create_patient(body: PatientIn, request: Request, u=STAFF):
    pid = new_id()
    save_patient(pid, body, u["id"], create=True)
    audit(u, "create", "patient", pid, None, request)
    return get_patient_or_404(pid)


@app.get("/api/patients/{pid}")
def get_patient(pid: str, request: Request, u=ANY):
    out = get_patient_or_404(pid)
    audit(u, "view", "patient", pid, None, request)
    if u["role"] != "receptionist":
        out["history"] = q("SELECT * FROM patient_history WHERE patient_id=? ORDER BY created_at DESC", (pid,))
    out["counts"] = q("""SELECT (SELECT count(*) FROM visits WHERE patient_id=:p AND deleted_at IS NULL) AS visits,
                                (SELECT count(*) FROM documents WHERE patient_id=:p AND deleted_at IS NULL) AS documents,
                                (SELECT count(*) FROM follow_ups WHERE patient_id=:p AND status='scheduled') AS followups""", {"p": pid}, one=True)
    return out


@app.put("/api/patients/{pid}")
def update_patient(pid: str, body: PatientIn, request: Request, u=STAFF):
    get_patient_or_404(pid)
    save_patient(pid, body)
    audit(u, "update", "patient", pid, None, request)
    return get_patient_or_404(pid)


@app.delete("/api/patients/{pid}", status_code=204)
def delete_patient(pid: str, request: Request, u=ADMIN):
    get_patient_or_404(pid)
    q("UPDATE patients SET deleted_at=? WHERE id=?", (now(), pid))
    index_patient(pid)
    audit(u, "delete", "patient", pid, None, request)


# ───────────────────────── history ─────────────────────────
@app.get("/api/patients/{pid}/history")
def get_history(pid: str, u=CLINICAL):
    get_patient_or_404(pid)
    return q("SELECT * FROM patient_history WHERE patient_id=? ORDER BY kind, created_at DESC", (pid,))


@app.post("/api/patients/{pid}/history", status_code=201)
def add_history(pid: str, body: HistoryIn, request: Request, u=CLINICAL):
    get_patient_or_404(pid)
    hid = new_id()
    q("INSERT INTO patient_history(id,patient_id,kind,description,since_date,created_by,created_at) VALUES (?,?,?,?,?,?,?)",
      (hid, pid, body.kind, body.description, iso(body.since_date), u["id"], now()))
    index_history(hid)
    audit(u, "create", "history", hid, None, request)
    return q("SELECT * FROM patient_history WHERE id=?", (hid,), one=True)


@app.put("/api/history/{hid}")
def update_history(hid: str, body: HistoryIn, request: Request, u=CLINICAL):
    if not q("SELECT 1 FROM patient_history WHERE id=?", (hid,), one=True):
        raise HTTPException(404, "Not found")
    q("UPDATE patient_history SET kind=?,description=?,since_date=? WHERE id=?", (body.kind, body.description, iso(body.since_date), hid))
    index_history(hid)
    audit(u, "update", "history", hid, None, request)
    return q("SELECT * FROM patient_history WHERE id=?", (hid,), one=True)


@app.delete("/api/history/{hid}", status_code=204)
def delete_history(hid: str, request: Request, u=CLINICAL):
    q("DELETE FROM patient_history WHERE id=?", (hid,))
    unidx("history", hid)
    audit(u, "delete", "history", hid, None, request)


# ───────────────────────── visits ─────────────────────────
def visit_with_rx(v):
    v = dict(v)
    v["prescriptions"] = q("SELECT * FROM prescriptions WHERE visit_id=? ORDER BY drug_name", (v["id"],))
    return v


def save_rx(vid, items):
    q("DELETE FROM prescriptions WHERE visit_id=?", (vid,))
    for r in items:
        q("INSERT INTO prescriptions(id,visit_id,drug_name,dose,route,frequency,duration,instructions) VALUES (?,?,?,?,?,?,?,?)",
          (new_id(), vid, r.drug_name, r.dose, r.route, r.frequency, r.duration, r.instructions))
    index_visit(vid)


def add_followup(pid, visit_id, due: date, reason, remind_days=1):
    fid = new_id()
    q("INSERT INTO follow_ups(id,patient_id,visit_id,due_date,reason,remind_at,created_at) VALUES (?,?,?,?,?,?,?)",
      (fid, pid, visit_id, iso(due), reason, iso(due - timedelta(days=remind_days)), now()))
    index_followup(fid)
    return q("SELECT * FROM follow_ups WHERE id=?", (fid,), one=True)


@app.get("/api/patients/{pid}/visits")
def list_visits(pid: str, u=CLINICAL):
    get_patient_or_404(pid)
    rows = q("""SELECT v.*, u.full_name AS doctor_name FROM visits v LEFT JOIN users u ON u.id=v.doctor_id
                WHERE v.patient_id=? AND v.deleted_at IS NULL ORDER BY v.visit_date DESC""", (pid,))
    return [visit_with_rx(v) for v in rows]


@app.post("/api/patients/{pid}/visits", status_code=201)
def create_visit(pid: str, body: VisitIn, request: Request, u=DOCTOR):
    get_patient_or_404(pid)
    vid = new_id()
    d = body.model_dump(exclude={"prescriptions", "follow_up_date", "follow_up_reason"})
    vdate = iso(d["visit_date"]) if d["visit_date"] else now()
    q("""INSERT INTO visits(id,patient_id,visit_date,chief_complaint,symptoms,examination,diagnosis,icd10_code,management_plan,
         physician_notes,doctor_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (vid, pid, vdate, d["chief_complaint"], d["symptoms"], d["examination"], d["diagnosis"], d["icd10_code"], d["management_plan"],
       d["physician_notes"], u["id"], now(), now()))
    save_rx(vid, body.prescriptions)
    if body.follow_up_date:
        add_followup(pid, vid, body.follow_up_date, body.follow_up_reason)
    audit(u, "create", "visit", vid, None, request)
    return visit_with_rx(q("SELECT * FROM visits WHERE id=?", (vid,), one=True))


@app.put("/api/visits/{vid}")
def update_visit(vid: str, body: VisitIn, request: Request, u=DOCTOR):
    cur = q("SELECT * FROM visits WHERE id=? AND deleted_at IS NULL", (vid,), one=True)
    if not cur:
        raise HTTPException(404, "Visit not found")
    d = body.model_dump(exclude={"prescriptions", "follow_up_date", "follow_up_reason"})
    q("""UPDATE visits SET visit_date=?,chief_complaint=?,symptoms=?,examination=?,diagnosis=?,icd10_code=?,management_plan=?,
         physician_notes=?,updated_at=? WHERE id=?""",
      (iso(d["visit_date"]) if d["visit_date"] else cur["visit_date"], d["chief_complaint"], d["symptoms"], d["examination"], d["diagnosis"],
       d["icd10_code"], d["management_plan"], d["physician_notes"], now(), vid))
    save_rx(vid, body.prescriptions)
    if body.follow_up_date:
        add_followup(cur["patient_id"], vid, body.follow_up_date, body.follow_up_reason)
    audit(u, "update", "visit", vid, None, request)
    return visit_with_rx(q("SELECT * FROM visits WHERE id=?", (vid,), one=True))


@app.delete("/api/visits/{vid}", status_code=204)
def delete_visit(vid: str, request: Request, u=DOCTOR):
    q("UPDATE visits SET deleted_at=? WHERE id=?", (now(), vid))
    index_visit(vid)
    audit(u, "delete", "visit", vid, None, request)


# ───────────────────────── documents + OCR ─────────────────────────
def sniff_mime(b: bytes) -> str:
    """Decide the type from the file's own bytes (the filename and the browser's claim are not trusted)."""
    if b[:5] == b"%PDF-":
        return "application/pdf"
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if b[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if b[:4] in (b"II*\x00", b"MM\x00*"):
        return "image/tiff"
    if b[:2] == b"BM":
        return "image/bmp"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    if b[128:132] == b"DICM":
        return "application/dicom"
    return "application/octet-stream"


def run_ocr(doc_id):
    d = q("SELECT storage_key, mime_type, ocr_status FROM documents WHERE id=? AND deleted_at IS NULL", (doc_id,), one=True)
    if not d:
        return
    q("UPDATE documents SET ocr_status='processing', ocr_error=NULL WHERE id=?", (doc_id,))
    try:
        with blob_file(d["storage_key"]) as p:
            text, status, langs = ocr.extract_text(p, d["mime_type"])
        q("UPDATE documents SET ocr_status=?, ocr_text=?, ocr_lang=? WHERE id=?", (status, text, langs, doc_id))
    except Exception as e:                       # noqa: BLE001 - record any failure on the row
        log.warning("OCR failed for %s: %s", doc_id, e)
        q("UPDATE documents SET ocr_status='failed', ocr_error=? WHERE id=?", (str(e)[:500], doc_id))
    index_document(doc_id)


def schedule_ocr(bg, did):
    """Local: after the response. Hosted (serverless): inline, because the function may stop once it has answered."""
    if USE_PG:
        run_ocr(did)
    else:
        bg.add_task(run_ocr, did)


def safe_doc(row):
    r = dict(row)
    r.pop("storage_key", None)
    return r


@app.get("/api/patients/{pid}/documents")
def list_documents(pid: str, u=CLINICAL):
    get_patient_or_404(pid)
    return q("""SELECT id,patient_id,visit_id,category,original_name,mime_type,size_bytes,ocr_status,ocr_lang,ocr_error,uploaded_at,
                substr(ocr_text,1,300) AS ocr_preview FROM documents WHERE patient_id=? AND deleted_at IS NULL ORDER BY uploaded_at DESC""", (pid,))


def store_document(pid, data: bytes, filename, category, visit_id, user):
    """Validate + save a file for a patient; returns (document_id, needs_ocr). Raises HTTPException on bad files."""
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "File larger than 25 MB")
    if not data:
        raise HTTPException(422, "Empty file")
    mime = sniff_mime(data)
    if mime not in ALLOWED_MIME:
        raise HTTPException(415, "File type is not allowed (PDF, PNG, JPEG, TIFF, BMP, WEBP, DICOM)")
    sha = hashlib.sha256(data).hexdigest()
    if q("SELECT 1 FROM documents WHERE patient_id=? AND sha256=? AND deleted_at IS NULL", (pid, sha), one=True):
        raise HTTPException(409, "This exact file is already attached to this patient")
    did, key = new_id(), f"{pid}/{uuid.uuid4().hex}"
    put_blob(key, data)
    name = os.path.basename((filename or "file").replace("\\", "/"))[:200]
    status = "not_applicable" if mime == "application/dicom" else "pending"
    q("""INSERT INTO documents(id,patient_id,visit_id,category,original_name,mime_type,size_bytes,storage_key,sha256,ocr_status,uploaded_by,uploaded_at)
         VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (did, pid, visit_id, category, name, mime, len(data), key, sha, status, user["id"], now()))
    index_document(did)
    return did, status == "pending"


@app.post("/api/patients/{pid}/documents", status_code=201)
async def upload_document(pid: str, bg: BackgroundTasks, request: Request, file: UploadFile = File(...),
                          category: str = Form("other"), visit_id: Optional[str] = Form(None), u=CLINICAL):
    get_patient_or_404(pid)
    if category not in ("lab", "imaging_report", "imaging_image", "operative_note", "other"):
        raise HTTPException(422, "Bad category")
    data = await file.read(MAX_UPLOAD + 1)
    did, needs_ocr = store_document(pid, data, file.filename, category, visit_id, u)
    if needs_ocr:
        schedule_ocr(bg, did)
    audit(u, "create", "document", did, {"name": file.filename}, request)
    return safe_doc(q("SELECT * FROM documents WHERE id=?", (did,), one=True))


def get_doc_or_404(did):
    d = q("SELECT * FROM documents WHERE id=? AND deleted_at IS NULL", (did,), one=True)
    if not d:
        raise HTTPException(404, "Document not found")
    return d


@app.get("/api/documents/{did}")
def get_document(did: str, u=CLINICAL):
    return safe_doc(get_doc_or_404(did))


@app.get("/api/documents/{did}/file")
def download_document(did: str, request: Request, u=CLINICAL):
    d = get_doc_or_404(did)
    audit(u, "download", "document", did, None, request)
    data = get_blob(d["storage_key"])
    if data is None:
        raise HTTPException(404, "File not found")
    return Response(data, media_type=d["mime_type"], headers={"Content-Disposition": "inline; filename*=UTF-8''" + quote(d["original_name"])})


@app.post("/api/documents/{did}/reocr", status_code=202)
def reocr(did: str, bg: BackgroundTasks, u=CLINICAL):
    d = get_doc_or_404(did)
    if d["mime_type"] == "application/dicom":
        raise HTTPException(422, "Nothing to read in a DICOM image")
    ocr.tesseract.cache_clear()                 # pick up a Tesseract installed after the app started
    schedule_ocr(bg, did)
    return {"queued": True}


@app.patch("/api/documents/{did}/ocr-text")
def correct_ocr(did: str, body: OcrTextIn, request: Request, u=CLINICAL):
    get_doc_or_404(did)
    q("UPDATE documents SET ocr_text=?, ocr_status='done' WHERE id=?", (body.ocr_text, did))
    index_document(did)
    audit(u, "update", "document", did, {"field": "ocr_text"}, request)
    return safe_doc(get_doc_or_404(did))


@app.delete("/api/documents/{did}", status_code=204)
def delete_document(did: str, request: Request, u=DOCTOR):
    get_doc_or_404(did)
    q("UPDATE documents SET deleted_at=? WHERE id=?", (now(), did))
    index_document(did)
    audit(u, "delete", "document", did, None, request)


# ───────────────────────── follow-ups ─────────────────────────
@app.get("/api/followups")
def list_followups(status: str = "scheduled", upto: Optional[date] = None, patient_id: Optional[str] = None,
                   limit: int = Query(200, le=500), u=ANY):
    rows = q("""SELECT f.*, p.full_name AS patient_name, p.phone AS patient_phone, p.mrn,
                       (f.status='scheduled' AND f.due_date < date('now','localtime')) AS overdue
                FROM follow_ups f JOIN patients p ON p.id=f.patient_id AND p.deleted_at IS NULL
                WHERE (?='all' OR f.status=?) AND (? IS NULL OR f.due_date <= ?) AND (? IS NULL OR f.patient_id=?)
                ORDER BY f.due_date LIMIT ?""", (status, status, iso(upto), iso(upto), patient_id, patient_id, limit))
    for r in rows:
        r["overdue"] = bool(r["overdue"])
    return rows


@app.post("/api/patients/{pid}/followups", status_code=201)
def create_followup(pid: str, body: FollowUpIn, request: Request, u=ANY):
    get_patient_or_404(pid)
    f = add_followup(pid, body.visit_id, body.due_date, body.reason, body.remind_days_before)
    audit(u, "create", "followup", f["id"], None, request)
    return f


@app.patch("/api/followups/{fid}")
def patch_followup(fid: str, body: FollowUpPatch, request: Request, u=ANY):
    cur = q("SELECT * FROM follow_ups WHERE id=?", (fid,), one=True)
    if not cur:
        raise HTTPException(404, "Not found")
    ch = body.model_dump(exclude_none=True)
    if "due_date" in ch:
        ch["due_date"] = iso(ch["due_date"])
    new = {**cur, **ch}
    q("UPDATE follow_ups SET status=?,due_date=?,reason=? WHERE id=?", (new["status"], new["due_date"], new["reason"], fid))
    index_followup(fid)
    audit(u, "update", "followup", fid, None, request)
    return q("SELECT * FROM follow_ups WHERE id=?", (fid,), one=True)


@app.get("/api/dashboard")
def dashboard(u=ANY):
    return q("""SELECT (SELECT count(*) FROM patients WHERE deleted_at IS NULL) AS patients,
                (SELECT count(*) FROM visits WHERE deleted_at IS NULL AND substr(visit_date,1,10) = date('now')) AS visits_today,
                (SELECT count(*) FROM follow_ups WHERE status='scheduled' AND due_date = date('now','localtime')) AS followups_today,
                (SELECT count(*) FROM follow_ups WHERE status='scheduled' AND due_date < date('now','localtime')) AS followups_overdue,
                (SELECT count(*) FROM documents WHERE ocr_status IN ('pending','processing') AND deleted_at IS NULL) AS ocr_queue,
                (SELECT count(*) FROM documents WHERE ocr_status='failed' AND deleted_at IS NULL) AS ocr_failed""", one=True)


# ───────────────────────── global search ─────────────────────────
def like_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def snippet(norm: str, terms: list[str]) -> str:
    pos = [norm.find(t) for t in terms if norm.find(t) >= 0]
    i = min(pos) if pos else 0
    seg = norm[max(0, i - 60): i + 140]
    for t in sorted(set(terms), key=len, reverse=True):
        seg = re.sub(re.escape(t), lambda m: "«" + m.group(0) + "»", seg)
    return ("…" if i > 60 else "") + seg + ("…" if len(norm) > i + 140 else "")


@app.get("/api/search")
def search(request: Request, qs: str = Query("", alias="q"), types: str = "", date_from: Optional[date] = None,
           date_to: Optional[date] = None, gender: Optional[str] = None, limit: int = Query(50, le=200), offset: int = 0, u=ANY):
    """Every term must match (AND), each as a substring of the normalised text of ANY field of ANY record
    (demographics, history, visits incl. prescriptions, follow-ups, OCR text). Whole-word matches rank first, then newest."""
    terms = [norm_text(t) for t in qs.split() if t.strip()][:8]
    if not terms and not (date_from or date_to or types):
        return {"total": 0, "hits": []}
    allowed = {"patient", "history", "visit", "document", "followup"}
    want = [t for t in types.split(",") if t in allowed]
    if u["role"] == "receptionist":
        want = [t for t in (want or allowed) if t in ("patient", "followup")]
    where, params = ["p.deleted_at IS NULL"], []
    for t in terms:
        where.append("s.norm LIKE ? ESCAPE '\\'")
        params.append(f"%{like_escape(t)}%")
    if want:
        where.append(f"s.source_type IN ({','.join('?' * len(want))})")
        params += want
    if date_from:
        where.append("s.event_date >= ?"); params.append(iso(date_from))
    if date_to:
        where.append("s.event_date < ?"); params.append(iso(date_to + timedelta(days=1)))
    if gender in ("male", "female", "other", "unknown"):
        where.append("p.gender = ?"); params.append(gender)
    rows = q(f"""SELECT s.source_type, s.source_id, s.patient_id, s.title, s.event_date, s.norm, p.full_name AS patient_name, p.mrn, p.phone
                 FROM search_index s JOIN patients p ON p.id = s.patient_id WHERE {' AND '.join(where)}
                 ORDER BY s.event_date DESC LIMIT 2000""", params)
    pats = [re.compile(r"(?<!\w)" + re.escape(t)) for t in terms]
    rows.sort(key=lambda r: -sum(1 for p in pats if p.search(r["norm"])))          # stable: newest first within equal rank
    total, page = len(rows), rows[offset: offset + limit]
    for r in page:
        r["snippet"] = snippet(r.pop("norm"), terms)
    audit(u, "search", "search", None, {"q": qs[:100], "n": total}, request)
    return {"total": total, "hits": page}


# ───────────────────────── admin ─────────────────────────
@app.get("/api/audit")
def get_audit(limit: int = Query(100, le=500), u=ADMIN):
    return q("""SELECT a.*, us.username FROM audit_log a LEFT JOIN users us ON us.id=a.user_id ORDER BY a.id DESC LIMIT ?""", (limit,))


class UserIn(BaseModel):
    username: str
    password: str = Field(min_length=8)
    full_name: str
    role: Literal["doctor", "nurse", "receptionist", "admin"]


@app.get("/api/users")
def list_users(u=ADMIN):
    return q("SELECT id, username, full_name, role, created_at FROM users ORDER BY created_at")


@app.post("/api/users", status_code=201)
def create_user(body: UserIn, request: Request, u=ADMIN):
    if q("SELECT 1 FROM users WHERE username=?", (body.username,), one=True):
        raise HTTPException(409, "Username taken")
    uid = new_id()
    q("INSERT INTO users(id,username,password_hash,full_name,role,created_at) VALUES (?,?,?,?,?,?)",
      (uid, body.username, hash_pw(body.password), body.full_name, body.role, now()))
    audit(u, "create", "user", uid, None, request)
    return {"id": uid, "username": body.username, "full_name": body.full_name, "role": body.role}


class PwIn(BaseModel):
    old_password: str
    new_password: str = Field(min_length=8)


@app.post("/api/auth/change-password", status_code=204)
def change_password(body: PwIn, request: Request, u=ANY):
    row = q("SELECT password_hash FROM users WHERE id=?", (u["id"],), one=True)
    if not bcrypt.checkpw(body.old_password.encode(), row["password_hash"].encode()):
        raise HTTPException(403, "Current password is wrong")
    q("UPDATE users SET password_hash=? WHERE id=?", (hash_pw(body.new_password), u["id"]))
    audit(u, "change_password", "user", u["id"], None, request)


# ───────────────────────── paper-sheet intake ─────────────────────────
INTAKE = (Path(tempfile.gettempdir()) / "ehr_intake") if USE_PG else DATA / "intake"      # working copy; hosted mode also keeps a copy in the database
INTAKE_MIME = {"application/pdf", "image/png", "image/jpeg", "image/tiff", "image/bmp", "image/webp"}


def intake_cleanup():
    """Uploaded sheets that were never saved are deleted after 2 days (they contain patient data)."""
    if USE_PG:
        q("DELETE FROM blobs WHERE key LIKE 'intake/%' AND created_at < ?", ((datetime.now(timezone.utc) - timedelta(days=2)).isoformat(timespec="seconds"),))
    if INTAKE.exists():
        cutoff = datetime.now().timestamp() - 2 * 86400
        for f in INTAKE.iterdir():
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
            except OSError:
                pass


def intake_load(iid: str):
    """(meta, bytes) of a pending sheet, or None. Hosted mode reads the database copy (another instance may have received the upload)."""
    import json
    if not re.fullmatch(r"[0-9a-f\-]{36}", iid or ""):
        return None
    if USE_PG:
        data, meta = get_blob(f"intake/{iid}"), get_blob(f"intake/{iid}.json")
        return (json.loads(meta), data) if data is not None and meta is not None else None
    if not (INTAKE / iid).exists():
        return None
    return json.loads((INTAKE / f"{iid}.json").read_text()), (INTAKE / iid).read_bytes()


def intake_drop(iid: str):
    for suffix in ("", ".json"):
        try:
            (INTAKE / f"{iid}{suffix}").unlink()
        except OSError:
            pass
        if USE_PG:
            del_blob(f"intake/{iid}{suffix}")


def find_duplicates(name: str, phone: Optional[str]):
    digits = re.sub(r"\D", "", norm_text(phone or ""))
    return q("""SELECT id, mrn, full_name, phone FROM patients WHERE deleted_at IS NULL
                AND ((? <> '' AND phone_digits = ?) OR norm_name = ?) LIMIT 5""", (digits, digits, norm_text(name or "")))


@app.get("/api/intake/status")
def intake_status(u=STAFF):
    try:
        langs = ocr.tesseract()[1]
    except Exception:                                      # noqa: BLE001
        langs = None
    return {"ai": bool(intake.ai_key()), "ocrspace": bool(intake.ocrspace_key()), "ocr": bool(langs), "ocr_langs": langs}


@app.post("/api/intake/extract")
def intake_extract(request: Request, file: UploadFile = File(...), mode: str = Form("auto"), u=STAFF):
    """Read a photographed/scanned patient sheet and return DRAFT fields. Nothing is saved to the patient record here."""
    data = file.file.read(MAX_UPLOAD + 1)
    if not data or len(data) > MAX_UPLOAD:
        raise HTTPException(413 if data else 422, "File is empty or larger than 25 MB")
    mime = sniff_mime(data)
    if mime not in INTAKE_MIME:
        raise HTTPException(415, "Please upload a photo (JPG/PNG/TIFF/WEBP) or a PDF of the sheet")
    intake_cleanup()
    iid = new_id()
    INTAKE.mkdir(parents=True, exist_ok=True)
    path = INTAKE / iid
    path.write_bytes(data)
    import json
    meta_json = json.dumps({"mime": mime, "name": os.path.basename((file.filename or "sheet").replace("\\", "/"))[:200], "user": u["id"]})
    (INTAKE / f"{iid}.json").write_text(meta_json)
    if USE_PG:
        put_blob(f"intake/{iid}", data)
        put_blob(f"intake/{iid}.json", meta_json.encode())
    warnings, result, engine, raw_text = [], None, None, ""
    if mode == "ai" or (mode == "auto" and intake.ai_key()):
        try:
            result, engine = intake.ai_extract(path, mime), "ai"
        except RuntimeError as e:
            warnings.append(str(e) + " — used the offline reader instead.")
    if result is None and (mode == "ocrspace" or (mode == "auto" and intake.ocrspace_key())):
        try:
            raw_text = intake.ocrspace_extract(path, mime)
            result, engine = intake.extract_fields(raw_text), "ocrspace"
            if not raw_text.strip():
                warnings.append("OCR.Space returned no text for this sheet.")
        except RuntimeError as e:
            warnings.append(str(e) + " — used the offline reader instead.")
    if result is None:
        try:
            text, _, _ = ocr.extract_text(path, mime)
            raw_text = text or ""
            result, engine = intake.extract_fields(raw_text), "local"
            try:
                langs = ocr.tesseract()[1]
            except Exception:                              # noqa: BLE001 - e.g. a PDF that already had a text layer
                langs = None
            if langs and "ara" not in langs:
                warnings.append("Arabic reading pack is not installed, so Arabic text may not be read. See README.")
            if not raw_text.strip():
                warnings.append("No text could be read from this sheet. Handwriting needs AI mode (see README) — or type the details yourself.")
        except Exception as e:                              # noqa: BLE001
            warnings.append(str(e))
            result, engine = {"fields": {k: None for k in intake.FIELDS}, "confidence": {}}, "none"
    f = result["fields"]
    audit(u, "intake_extract", "intake", iid, {"engine": engine}, request)
    return {"intake_id": iid, "mime": mime, "engine": engine, "fields": f, "confidence": result["confidence"], "raw_text": raw_text,
            "warnings": warnings, "duplicates": find_duplicates(f.get("full_name"), f.get("phone"))}


@app.get("/api/intake/{iid}/file")
def intake_file(iid: str, u=STAFF):
    import json
    got = intake_load(iid)
    if not got:
        raise HTTPException(404, "Not found")
    meta, data = got
    if meta["user"] != u["id"] and u["role"] != "admin":
        raise HTTPException(403, "Not your upload")
    return Response(data, media_type=meta["mime"], headers={"Content-Disposition": "inline"})


class IntakeCommit(BaseModel):
    intake_id: Optional[str] = None
    patient: PatientIn
    past_history: Optional[str] = None
    chief_complaint: Optional[str] = None
    symptoms: Optional[str] = None
    examination: Optional[str] = None
    diagnosis: Optional[str] = None
    management_plan: Optional[str] = None
    physician_notes: Optional[str] = None
    follow_up_date: Optional[date] = None
    follow_up_reason: Optional[str] = None
    force: bool = False


@app.post("/api/intake/commit", status_code=201)
def intake_commit(body: IntakeCommit, request: Request, u=STAFF):
    """Save the REVIEWED draft: patient (any staff), history (clinical roles), visit + follow-up (doctor/admin), and attach the sheet image."""
    import json
    from fastapi.responses import JSONResponse
    dups = find_duplicates(body.patient.full_name, body.patient.phone)
    if dups and not body.force:
        return JSONResponse({"detail": "Possible duplicate patient", "duplicates": dups}, status_code=409)
    clinical, doctor = u["role"] in ("doctor", "nurse", "admin"), u["role"] in ("doctor", "admin")
    pid, skipped = new_id(), []
    save_patient(pid, body.patient, u["id"], create=True)
    if body.past_history and body.past_history.strip():
        if clinical:
            hid = new_id()
            q("INSERT INTO patient_history(id,patient_id,kind,description,created_by,created_at) VALUES (?,?,?,?,?,?)",
              (hid, pid, "medical", body.past_history.strip(), u["id"], now()))
            index_history(hid)
        else:
            skipped.append("past_history")
    visit_fields = [x for x in (body.chief_complaint, body.symptoms, body.examination, body.diagnosis, body.management_plan, body.physician_notes) if x and x.strip()]
    if visit_fields:
        if doctor:
            vid = new_id()
            q("""INSERT INTO visits(id,patient_id,visit_date,chief_complaint,symptoms,examination,diagnosis,management_plan,physician_notes,doctor_id,created_at,updated_at)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (vid, pid, now(), body.chief_complaint, body.symptoms, body.examination, body.diagnosis,
                                                      body.management_plan, body.physician_notes, u["id"], now(), now()))
            index_visit(vid)
            if body.follow_up_date:
                add_followup(pid, vid, body.follow_up_date, body.follow_up_reason)
        else:
            skipped.append("visit")
    elif body.follow_up_date:
        add_followup(pid, None, body.follow_up_date, body.follow_up_reason)
    attached = False
    pending_sheet = intake_load(body.intake_id) if body.intake_id else None
    if pending_sheet:
        meta, sheet_bytes = pending_sheet
        if clinical and meta["user"] == u["id"]:
            try:
                did, needs_ocr = store_document(pid, sheet_bytes, meta["name"], "other", None, u)
                attached = True
                if needs_ocr:
                    if USE_PG:
                        run_ocr(did)
                    else:
                        threading.Thread(target=run_ocr, args=(did,), daemon=True).start()
            except HTTPException:
                pass
        intake_drop(body.intake_id)                           # the temporary copy is always removed once saved
    audit(u, "intake_commit", "patient", pid, {"skipped": skipped, "attached": attached}, request)
    return {"patient": get_patient_or_404(pid), "skipped": skipped, "sheet_attached": attached}


# ───────────────────────── settings (admin) ─────────────────────────
@app.get("/api/settings")
def get_settings(u=ADMIN):
    return {"ai": bool(intake.ai_key()), "ai_from_env": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "ocrspace": bool(intake.ocrspace_key()), "ocrspace_from_env": bool(os.environ.get("OCRSPACE_API_KEY"))}


class KeyIn(BaseModel):
    key: str = ""


@app.post("/api/settings/ai-key", status_code=204)
def set_ai_key(body: KeyIn, request: Request, u=ADMIN):
    """Admin stores (or clears, with an empty value) the Anthropic API key used for AI sheet reading. The key is never returned."""
    k = body.key.strip()
    if k and (len(k) < 20 or not k.startswith("sk-")):
        raise HTTPException(422, "That does not look like an Anthropic API key (it starts with sk-)")
    kv_set("anthropic_api_key", k)
    audit(u, "update", "settings", None, {"ai_key": "set" if k else "cleared"}, request)


@app.post("/api/settings/ocrspace-key", status_code=204)
def set_ocrspace_key(body: KeyIn, request: Request, u=ADMIN):
    """Admin stores (or clears) the OCR.Space API key. The key is never returned."""
    k = body.key.strip()
    if k and (len(k) < 8 or not re.fullmatch(r"[A-Za-z0-9._\-]+", k)):
        raise HTTPException(422, "That does not look like an OCR.Space API key")
    kv_set("ocrspace_api_key", k)
    audit(u, "update", "settings", None, {"ocrspace_key": "set" if k else "cleared"}, request)


if USE_PG:
    init_db()                                    # idempotent; also makes cold starts on serverless hosts self-sufficient

FRONT = ROOT / "frontend"
if FRONT.exists():
    app.mount("/", StaticFiles(directory=FRONT, html=True), name="ui")
