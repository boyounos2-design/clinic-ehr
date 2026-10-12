"""End-to-end smoke test against a running server:  python backend/smoke_test.py [http://localhost:8000]"""
import io, sys, time
import httpx
from PIL import Image, ImageDraw, ImageFont

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
c = httpx.Client(base_url=BASE, timeout=60)
ok = fail = 0
def check(name, cond, extra=""):
    global ok, fail
    ok, fail = (ok + 1, fail) if cond else (ok, fail + 1)
    print(("PASS " if cond else "FAIL ") + name, extra if not cond else "")
def login(u, p):
    r = c.post("/api/auth/login", json={"username": u, "password": p}); r.raise_for_status()
    return {"Authorization": "Bearer " + r.json()["token"]}

check("bad login rejected", c.post("/api/auth/login", json={"username": "doctor", "password": "x"}).status_code == 401)
check("no token rejected", c.get("/api/patients").status_code == 401)
D, R, N = login("doctor", "Doctor#12345"), login("reception", "Desk#12345"), login("nurse", "Nurse#12345")

p = c.post("/api/patients", headers=R, json={"full_name": "سارة إبراهيم", "date_of_birth": "1990-05-01",
          "phone": "0100 555 7788", "address": "Luxor", "gender": "female"}).json()
pid = p["id"]
check("receptionist creates patient, age computed", p["age_years"] >= 30, p)
check("receptionist blocked from visits", c.get(f"/api/patients/{pid}/visits", headers=R).status_code == 403)
check("nurse cannot write visit", c.post(f"/api/patients/{pid}/visits", headers=N, json={}).status_code == 403)

c.post(f"/api/patients/{pid}/history", headers=D, json={"kind": "allergy", "description": "Penicillin allergy"})
v = c.post(f"/api/patients/{pid}/visits", headers=D, json={
    "chief_complaint": "Knee pain", "examination": "Effusion, McMurray positive", "diagnosis": "Medial meniscus tear",
    "management_plan": "MRI then arthroscopy", "follow_up_date": "2026-11-01", "follow_up_reason": "MRI review",
    "prescriptions": [{"drug_name": "Diclofenac", "dose": "75 mg", "frequency": "BD"}]})
check("visit created", v.status_code == 201, v.text)

# document with OCR: render known text to an image
img = Image.new("RGB", (900, 260), "white"); d = ImageDraw.Draw(img)
try: font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 40)
except OSError: font = ImageFont.load_default()
d.text((30, 40), "HbA1c 7.9 percent", fill="black", font=font); d.text((30, 120), "Creatinine 1.1 mg/dl", fill="black", font=font)
buf = io.BytesIO(); img.save(buf, "PNG")
up = c.post(f"/api/patients/{pid}/documents", headers=D, data={"category": "lab"}, files={"file": ("lab.png", buf.getvalue(), "image/png")})
check("upload accepted", up.status_code == 201, up.text); did = up.json()["id"]
check("duplicate upload rejected", c.post(f"/api/patients/{pid}/documents", headers=D, files={"file": ("again.png", buf.getvalue(), "image/png")}).status_code == 409)
check("disguised exe rejected", c.post(f"/api/patients/{pid}/documents", headers=D, files={"file": ("x.png", b"MZ\x90\x00" + b"0" * 200, "image/png")}).status_code == 415)
for _ in range(60):
    st = c.get(f"/api/documents/{did}", headers=D).json()
    if st["ocr_status"] in ("done", "failed"): break
    time.sleep(1)
check("OCR finished", st["ocr_status"] == "done", st)
check("OCR text extracted", "7.9 percent" in (st.get("ocr_text") or "").lower(), st.get("ocr_text"))

def S(q, h=D, **kw): return c.get("/api/search", headers=h, params={"q": q, **kw}).json()
def hit(res, pid_, typ): return any(h["patient_id"] == pid_ and h["source_type"] == typ for h in res["hits"])
check("search: name partial", hit(S("ساره"), pid, "patient"), S("ساره"))           # ة/ه + أ/ا normalisation: سارة vs ساره
check("search: alef variants", hit(S("ابراهيم"), pid, "patient"))                    # إبراهيم typed with plain alef
check("search: phone fragment", hit(S("5557788"), pid, "patient"))
check("search: arabic-indic digits", hit(S("٥٥٥٧٧٨٨"), pid, "patient"))
check("search: diagnosis", hit(S("meniscus"), pid, "visit"))
check("search: drug name", hit(S("diclofenac"), pid, "visit"))
check("search: history keyword", hit(S("penicillin"), pid, "history"))
check("search: OCR content", hit(S("creatinine"), pid, "document"), S("creatinine"))
check("search: multi-term AND", hit(S("knee arthroscopy"), pid, "visit") and not S("knee zzzzqq")["hits"])
check("search: follow-up reason", hit(S("MRI review"), pid, "followup"))
check("search: date", hit(S("2026-11-01"), pid, "followup"), S("2026-11-01"))
check("search: type filter", all(h["source_type"] == "document" for h in S("creatinine", types="document")["hits"]))
check("search: receptionist sees no clinical hits", not S("meniscus", h=R)["hits"])
check("search: LIKE wildcards are literal", S("%")["hits"] == [] and S("_")["hits"] == [])
check("search: demo Arabic data", S("الصليبي")["total"] >= 1)

fu = c.get("/api/followups", headers=D, params={"patient_id": pid}).json()
check("follow-up listed", len(fu) == 1)
check("follow-up marked done", c.patch(f"/api/followups/{fu[0]['id']}", headers=D, json={"status": "done"}).json()["status"] == "done")
check("deleted patient disappears from search", (c.delete(f"/api/patients/{pid}", headers=login("admin", "Admin#12345")).status_code == 204) and not S("creatinine")["hits"])
check("audit log has entries", len(c.get("/api/audit", headers=login("admin", "Admin#12345")).json()) > 5)
print(f"\n{ok} passed, {fail} failed"); sys.exit(1 if fail else 0)
