"""Paper-sheet intake: turn a photo/scan of a patient sheet into draft form fields.

Two engines (the doctor ALWAYS reviews the draft before anything is saved):
  * local - Tesseract OCR text -> rule-based parser (Arabic + English labels). Offline, free. Printed/typed text only.
  * ai    - Claude vision reads the sheet directly (handles handwriting). Needs an Anthropic API key; the sheet image
            is sent to Anthropic's API, so it is OFF unless a key is configured.
"""
import base64
import io
import json
import os
import re
import unicodedata
from datetime import date, timedelta
from pathlib import Path

# ───────────────────────── normalisation (shared with search) ─────────────────────────
_AR = str.maketrans({"ى": "ي", "ة": "ه", "ـ": None, **{c: str(i) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩")},
                     **{c: str(i) for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")}})


def norm_text(t) -> str:
    """lower-case, strip Latin accents and Arabic diacritics, unify أإآٱ→ا ى→ي ة→ه, Arabic digits→0-9."""
    s = unicodedata.normalize("NFKD", str(t or "")).lower()
    s = "".join(c for c in s if not unicodedata.combining(c)).replace("ٱ", "ا")
    return s.translate(_AR)


# ───────────────────────── rule-based parser ─────────────────────────
FIELDS = ["full_name", "age", "dob", "phone", "address", "gender", "past_history", "chief_complaint", "symptoms",
          "examination", "diagnosis", "management_plan", "follow_up", "physician_notes"]
MULTILINE = {"past_history", "chief_complaint", "symptoms", "examination", "diagnosis", "management_plan", "address", "physician_notes"}

_LABELS = {
    "full_name": ["اسم المريض", "الاسم", "اسم", "patient name", "name", "patient", "pt"],
    "age": ["السن", "العمر", "سن", "age"],
    "dob": ["تاريخ الميلاد", "الميلاد", "date of birth", "dob", "birth date"],
    "phone": ["رقم التليفون", "رقم الهاتف", "رقم الموبايل", "رقم المحمول", "التليفون", "تليفون", "الهاتف", "هاتف", "الموبايل", "موبايل",
              "المحمول", "محمول", "تلفون", "phone number", "phone", "mobile", "tel", "contact", "ت"],
    "address": ["محل الاقامه", "العنوان", "عنوان", "السكن", "address", "residence", "city"],
    "gender": ["النوع", "الجنس", "gender", "sex"],
    "past_history": ["التاريخ المرضي", "تاريخ مرضي", "التاريخ السابق", "past medical history", "past history", "medical history", "pmh", "h/o", "history", "ph"],
    "chief_complaint": ["الشكوي الرئيسيه", "الشكوي", "شكوي", "chief complaint", "complaint", "c/o", "cc"],
    "symptoms": ["الاعراض", "اعراض", "symptoms"],
    "examination": ["الفحص الاكلينيكي", "الفحص", "فحص", "on examination", "examination", "exam", "o/e", "findings"],
    "diagnosis": ["التشخيص الاكلينيكي", "التشخيص", "تشخيص", "diagnosis", "impression", "dx"],
    "management_plan": ["خطه العلاج", "الخطه", "العلاج", "management plan", "management", "treatment", "plan", "rx", "tx"],
    "follow_up": ["موعد المتابعه", "الزياره القادمه", "المتابعه", "follow up", "follow-up", "next visit", "f/u", "fu", "review"],
}
_LABEL_TOKENS = {f: sorted(([t for t in norm_text(l).split()] for l in ls), key=lambda x: -len(x)) for f, ls in _LABELS.items()}
_SEP = ":：-–—=.،,"
_MALE = {"ذكر", "male", "m", "ولد", "رجل", "ذكرا"}
_FEMALE = {"انثي", "female", "f", "بنت", "سيده", "انسه", "امراه", "انثى"}


def _strip_sep(s: str) -> str:
    return s.strip(" \t" + _SEP)


def _match_label(line: str):
    """Returns (field, value_text) if the line starts with a known label, else None."""
    line = re.sub(r"([:：])(?=\S)", r"\1 ", line, count=1)           # 'الاسم:احمد' -> 'الاسم: احمد'
    toks = line.split()
    ntoks = [norm_text(t).strip(_SEP) for t in toks]
    for field, variants in _LABEL_TOKENS.items():
        for lab in variants:
            k = len(lab)
            if len(ntoks) >= k and ntoks[:k] == lab:
                # short ambiguous labels must be followed by a separator to count (avoid 'ت' / 'ph' inside words)
                raw_lab = " ".join(toks[:k])
                if len(" ".join(lab)) <= 2 and not re.search(r"[:：\-–=]", raw_lab + (line[len(raw_lab):len(raw_lab) + 2])):
                    continue
                return field, _strip_sep(" ".join(toks[k:]))
    return None


def _parse_date(s: str):
    s = norm_text(s)
    m = re.search(r"(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})", s)
    cands = []
    if m:
        cands.append((int(m[1]), int(m[2]), int(m[3])))
    m = re.search(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})", s)
    if m:
        y = int(m[3]) + (2000 if int(m[3]) < 100 and int(m[3]) <= date.today().year % 100 else 1900 if int(m[3]) < 100 else 0)
        cands.append((y, int(m[2]), int(m[1])))                      # day-first (Egypt)
    for y, mo, d in cands:
        try:
            return date(y, mo, d)
        except ValueError:
            continue
    return None


def _relative_date(s: str):
    n = norm_text(s)
    m = re.search(r"(?:بعد|after|in)\s*(\d+)?\s*(اسبوعين|اسبوع|اسابيع|week|weeks|wk|wks|ايام|يوم|day|days|شهرين|شهر|اشهر|month|months)", n)
    if not m:
        return None
    k = int(m[1]) if m[1] else (2 if m[2] in ("اسبوعين", "شهرين") else 1)
    unit = m[2]
    days = 7 if unit.startswith(("اسب", "week", "wk")) else 1 if unit.startswith(("ايام", "يوم", "day")) else 30
    return date.today() + timedelta(days=k * days)


def _phone(s: str):
    d = re.sub(r"[^\d+]", "", norm_text(s))
    m = re.search(r"(?:\+?20|0)?(1[0125]\d{8})", d)                    # Egyptian mobiles
    if m:
        return "0" + m[1]
    digits = re.sub(r"\D", "", d)
    return digits if 7 <= len(digits) <= 15 else None


def _gender(s: str):
    for w in norm_text(s).replace("/", " ").split():
        w = w.strip(_SEP)
        if w in {norm_text(x) for x in _MALE}:
            return "male"
        if w in {norm_text(x) for x in _FEMALE}:
            return "female"
    return None


def _age(s: str):
    m = re.search(r"(\d{1,3})", norm_text(s))
    return int(m[1]) if m and 0 <= int(m[1]) <= 120 else None


def extract_fields(text: str) -> dict:
    """Parse raw sheet text into fields. Returns {"fields": {...}, "confidence": {field: 'high'|'low'}}."""
    raw: dict[str, list[str]] = {}
    loose: list[str] = []
    cur = None
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            cur = None if cur not in MULTILINE else cur
            continue
        hit = _match_label(line)
        if hit:
            cur, val = hit
            raw.setdefault(cur, [])
            if val:
                raw[cur].append(val)
        elif cur in MULTILINE:
            raw[cur].append(line)
        else:
            loose.append(line)
            cur = None
    f: dict = {k: None for k in FIELDS}
    conf: dict = {}

    def put(k, v, c="high"):
        if v not in (None, ""):
            f[k] = v
            conf[k] = c

    j = lambda k: "\n".join(raw.get(k, [])).strip()
    put("full_name", re.sub(r"\s+", " ", j("full_name")))
    if j("age"):
        put("age", _age(j("age")))
    if j("dob"):
        put("dob", (_parse_date(j("dob")) or None) and _parse_date(j("dob")).isoformat())
    if j("phone"):
        put("phone", _phone(j("phone")))
    put("address", j("address"))
    if j("gender"):
        put("gender", _gender(j("gender")))
    for k in ("past_history", "chief_complaint", "symptoms", "examination", "diagnosis", "management_plan"):
        put(k, j(k))
    if j("follow_up"):
        fu = _parse_date(j("follow_up")) or _relative_date(j("follow_up"))
        put("follow_up", fu.isoformat() if fu else None)
        f["follow_up_reason"] = j("follow_up") if not fu else None

    # fallbacks for fields the sheet did not label -> marked low confidence so the doctor looks twice
    blob = "\n".join(loose + [v for vs in raw.values() for v in vs])
    if not f["phone"]:
        put("phone", _phone(next((l for l in loose if _phone(l)), "") or ""), "low")
    if f["age"] is None and f["dob"] is None:
        m = re.search(r"(\d{1,3})\s*(?:سنه|سنة|عام|y\.?o\.?|yrs?|years?|y\b)", norm_text(blob))
        if m and int(m[1]) <= 120:
            put("age", int(m[1]), "low")
    if not f["gender"]:
        put("gender", _gender(" ".join(loose)), "low")
    if not f["full_name"]:
        first = next((l for l in loose if len(l.split()) <= 5 and not re.search(r"\d{5,}", norm_text(l))), None)
        if first:
            put("full_name", re.sub(r"\s+", " ", first), "low")
    def residual(line: str) -> str:
        """what is left of a loose line after removing the parts already captured (phone, gender word, age phrase)"""
        r = line
        if f["phone"] and _phone(line):
            return ""
        r = re.sub(r"\d{1,3}\s*(?:سنه|سنة|عام|y\.?o\.?|yrs?|years?|y\b)", " ", r, flags=re.I)
        words = [w for w in r.split() if norm_text(w).strip(_SEP) not in {norm_text(x) for x in (_MALE | _FEMALE)}]
        return " ".join(words).strip(_SEP + " ")
    left = [x for x in (residual(l) for l in loose if l != f["full_name"]) if x]
    put("physician_notes", "\n".join(left), "low")
    if f["dob"]:
        f["age"] = None
    return {"fields": f, "confidence": conf}


# ───────────────────────── AI engine (Claude vision) ─────────────────────────
AI_MODEL = os.environ.get("EHR_AI_MODEL", "claude-sonnet-5-5")
PROMPT = """You are reading a photographed or scanned paper sheet from an orthopedic clinic in Egypt. The text may be Arabic, English or mixed, printed or handwritten.
Return ONLY one JSON object (no markdown) with exactly these keys, using null when the sheet does not contain that item:
full_name, age (integer years), dob (YYYY-MM-DD), phone (digits only), address, gender ("male"|"female"|null),
past_history, chief_complaint, symptoms, examination, diagnosis, management_plan, follow_up (YYYY-MM-DD if a date or relative time like 'after 2 weeks' is written; compute from today's date {today}), follow_up_reason, physician_notes (anything else written on the sheet that fits nowhere above),
uncertain (array of key names whose value you could not read confidently).
Rules: copy text exactly as written and keep its language; never invent or guess a value; do not translate; if a word is illegible write what you can read and list the key in "uncertain"."""


def _file_kv(name: str):
    f = Path(os.environ.get("EHR_DATA_DIR", Path(__file__).resolve().parent.parent / "data")) / f"{name}.txt"
    return (f.read_text().strip() or None) if f.exists() else None


kv_get = _file_kv        # the app replaces this with a database-backed version in hosted mode


def ai_key() -> str | None:
    k = os.environ.get("ANTHROPIC_API_KEY")
    if k and k.strip():
        return k.strip()
    return kv_get("anthropic_api_key")


def _prepare_image(path: Path, mime: str):
    """Returns (media_type, base64) for the API: PDFs go as-is, images are normalised to JPEG <= 2000px."""
    if mime == "application/pdf":
        return "application/pdf", base64.b64encode(path.read_bytes()).decode()
    from PIL import Image, ImageOps
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((2000, 2000))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=88)
    return "image/jpeg", base64.b64encode(buf.getvalue()).decode()


def ai_extract(path: Path, mime: str, client=None) -> dict:
    """Ask Claude to read the sheet. Raises RuntimeError with a readable message on any failure."""
    import httpx
    key = ai_key()
    if not key:
        raise RuntimeError("AI mode is not configured (no API key).")
    media, data = _prepare_image(path, mime)
    block = ({"type": "document", "source": {"type": "base64", "media_type": media, "data": data}} if media == "application/pdf"
             else {"type": "image", "source": {"type": "base64", "media_type": media, "data": data}})
    body = {"model": AI_MODEL, "max_tokens": 2000,
            "messages": [{"role": "user", "content": [block, {"type": "text", "text": PROMPT.format(today=date.today().isoformat())}]}]}
    try:
        c = client or httpx.Client(timeout=90)
        r = c.post("https://api.anthropic.com/v1/messages", json=body,
                   headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    except Exception as e:                                                # noqa: BLE001
        raise RuntimeError(f"Could not reach the AI service: {e}") from e
    if r.status_code != 200:
        raise RuntimeError(f"AI service returned {r.status_code}: {r.text[:200]}")
    txt = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text").strip()
    txt = re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.M).strip()
    try:
        obj = json.loads(txt[txt.index("{"): txt.rindex("}") + 1])
    except (ValueError, json.JSONDecodeError) as e:
        raise RuntimeError("The AI answer was not readable as data.") from e
    return normalise_ai(obj)


# ───────────────────────── OCR.Space engine (online OCR, text only) ─────────────────────────
OCRSPACE_URL = os.environ.get("EHR_OCRSPACE_URL", "https://api.ocr.space/parse/image")
OCRSPACE_LIMIT = 1024 * 1024 - 20_000          # free plan: files up to 1 MB


def _data_file(name: str) -> Path:
    return Path(os.environ.get("EHR_DATA_DIR", Path(__file__).resolve().parent.parent / "data")) / name


def ocrspace_key() -> str | None:
    k = os.environ.get("OCRSPACE_API_KEY")
    if k and k.strip():
        return k.strip()
    return kv_get("ocrspace_api_key")


def _shrink_for_ocrspace(path: Path, mime: str):
    """Returns (filename, bytes, content_type). PDFs are sent as-is; photos are re-encoded as JPEG under the 1 MB free-plan limit."""
    if mime == "application/pdf":
        data = path.read_bytes()
        if len(data) > OCRSPACE_LIMIT:
            raise RuntimeError("OCR.Space free plan accepts files up to 1 MB - upload a smaller PDF or a photo instead.")
        return "sheet.pdf", data, "application/pdf"
    from PIL import Image, ImageOps
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        side, q = 2400, 85
        while True:
            im2 = im.copy()
            im2.thumbnail((side, side))
            buf = io.BytesIO()
            im2.save(buf, "JPEG", quality=q)
            if buf.tell() <= OCRSPACE_LIMIT or side <= 800:
                return "sheet.jpg", buf.getvalue(), "image/jpeg"
            side, q = int(side * 0.8), max(60, q - 5)


def ocrspace_extract(path: Path, mime: str, client=None) -> str:
    """Send the sheet to OCR.Space (Engine 3: handwriting + Arabic) and return the plain text. Raises RuntimeError with a readable message."""
    import httpx
    key = ocrspace_key()
    if not key:
        raise RuntimeError("OCR.Space is not configured (no API key).")
    name, data, ctype = _shrink_for_ocrspace(path, mime)
    try:
        c = client or httpx.Client(timeout=120)
        r = c.post(OCRSPACE_URL, headers={"apikey": key}, files={"file": (name, data, ctype)},
                   data={"language": "auto", "OCREngine": "3", "detectOrientation": "true", "scale": "true", "isOverlayRequired": "false"})
    except Exception as e:                                                # noqa: BLE001
        raise RuntimeError(f"Could not reach OCR.Space: {e}") from e
    if r.status_code != 200:
        raise RuntimeError(f"OCR.Space returned {r.status_code}: {r.text[:200]}")
    try:
        j = r.json()
    except ValueError as e:
        raise RuntimeError("OCR.Space answer was not readable.") from e
    if j.get("IsErroredOnProcessing"):
        m = j.get("ErrorMessage")
        raise RuntimeError("OCR.Space: " + ("; ".join(m) if isinstance(m, list) else str(m or "processing failed")))
    return "\n".join((p.get("ParsedText") or "").strip() for p in (j.get("ParsedResults") or [])).strip()


def normalise_ai(obj: dict) -> dict:
    f = {k: obj.get(k) for k in FIELDS}
    f["follow_up_reason"] = obj.get("follow_up_reason")
    if f["age"] is not None:
        try:
            f["age"] = int(f["age"])
        except (TypeError, ValueError):
            f["age"] = None
    f["phone"] = _phone(str(f["phone"])) if f["phone"] else None
    f["gender"] = f["gender"] if f["gender"] in ("male", "female") else (_gender(str(f["gender"])) if f["gender"] else None)
    for k in ("dob", "follow_up"):
        d = _parse_date(str(f[k])) if f[k] else None
        f[k] = d.isoformat() if d else None
    unc = set(obj.get("uncertain") or [])
    conf = {k: ("low" if k in unc else "high") for k, v in f.items() if v not in (None, "")}
    return {"fields": f, "confidence": conf}
