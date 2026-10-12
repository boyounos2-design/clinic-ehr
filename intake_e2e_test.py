"""End-to-end test of paper-sheet intake against a running server:  python intake_e2e_test.py [url]"""
import io, sys, httpx
from PIL import Image, ImageDraw, ImageFont
base = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
c = httpx.Client(base_url=base, timeout=120); ok = fail = 0
def check(n, cond, extra=""):
    global ok, fail; ok, fail = (ok + 1, fail) if cond else (ok, fail + 1); print(("PASS " if cond else "FAIL ") + n, "" if cond else extra)
def login(u, p): return {"Authorization": "Bearer " + c.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}
D, R, N = login("doctor", "Doctor#12345"), login("reception", "Desk#12345"), login("nurse", "Nurse#12345")

lines = ["Name: Karim Adel Saleh", "Age: 47", "Sex: Male", "Mobile: 01066778899", "Address: Armant, Luxor", "PMH: Hypertension",
         "C/O: Right shoulder pain 3 months", "O/E: Painful arc, positive Neer test", "Dx: Rotator cuff tendinopathy", "Rx: Physiotherapy and NSAIDs", "F/U: after 2 weeks"]
img = Image.new("RGB", (1300, 120 + 62 * len(lines)), "white"); d = ImageDraw.Draw(img)
font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 40)
for i, l in enumerate(lines): d.text((50, 50 + 62 * i), l, fill="black", font=font)
buf = io.BytesIO(); img.save(buf, "PNG"); png = buf.getvalue()

st = c.get("/api/intake/status", headers=D).json(); print("status:", st)
r = c.post("/api/intake/extract", headers=D, files={"file": ("sheet.png", png, "image/png")}, data={"mode": "local"})
check("extract returns 200", r.status_code == 200, r.text); x = r.json(); f = x["fields"]
check("engine is local", x["engine"] == "local", x["engine"])
check("name read", f["full_name"] == "Karim Adel Saleh", f["full_name"])
check("age/gender/phone read", (f["age"], f["gender"], f["phone"]) == (47, "male", "01066778899"), (f["age"], f["gender"], f["phone"]))
check("clinical fields read", all(f[k] for k in ("past_history", "chief_complaint", "examination", "diagnosis", "management_plan")), f)
check("follow-up date computed", f["follow_up"] is not None, f["follow_up"])
check("preview file served to its owner only", c.get(f"/api/intake/{x['intake_id']}/file", headers=D).status_code == 200 and c.get(f"/api/intake/{x['intake_id']}/file", headers=N).status_code == 403)
check("non-image rejected", c.post("/api/intake/extract", headers=D, files={"file": ("x.png", b"MZ" + b"0" * 300, "image/png")}).status_code == 415)
check("ai mode without key falls back with a warning", (lambda j: j["engine"] == "local" and any("AI" in w for w in j["warnings"]))(
    c.post("/api/intake/extract", headers=D, files={"file": ("s.png", png, "image/png")}, data={"mode": "ai"}).json()))

body = {"intake_id": x["intake_id"], "patient": {"full_name": f["full_name"], "age_years": f["age"], "phone": f["phone"], "address": f["address"], "gender": f["gender"]},
        "past_history": f["past_history"], "chief_complaint": f["chief_complaint"], "examination": f["examination"], "diagnosis": f["diagnosis"],
        "management_plan": f["management_plan"], "follow_up_date": f["follow_up"], "follow_up_reason": "review"}
sv = c.post("/api/intake/commit", headers=D, json=body); check("doctor commit 201", sv.status_code == 201, sv.text); p = sv.json()["patient"]
check("approximate age stored and flagged", (p["age_years"], p["dob_approx"]) == (47, 1), p)
check("sheet attached", sv.json()["sheet_attached"] is True and len(c.get(f"/api/patients/{p['id']}/documents", headers=D).json()) == 1)
check("visit + history + follow-up created", len(c.get(f"/api/patients/{p['id']}/visits", headers=D).json()) == 1 and len(c.get(f"/api/patients/{p['id']}/history", headers=D).json()) == 1 and len(c.get("/api/followups", headers=D, params={"patient_id": p["id"]}).json()) == 1)
check("temp copy removed after commit", c.get(f"/api/intake/{x['intake_id']}/file", headers=D).status_code == 404)
check("new patient is searchable by diagnosis", any(h["patient_id"] == p["id"] for h in c.get("/api/search", headers=D, params={"q": "tendinopathy"}).json()["hits"]))
check("approximate DOB is not searchable as a date", not any(h["patient_id"] == p["id"] for h in c.get("/api/search", headers=D, params={"q": f"{p['date_of_birth']}"}).json()["hits"]))
dup = c.post("/api/intake/commit", headers=D, json={**body, "intake_id": None}); check("duplicate (same phone) warned with 409", dup.status_code == 409 and dup.json()["duplicates"], dup.text)
check("duplicate allowed with force", c.post("/api/intake/commit", headers=D, json={**body, "intake_id": None, "force": True}).status_code == 201)
rc = c.post("/api/intake/commit", headers=R, json={"patient": {"full_name": "Desk Patient", "age_years": 30, "phone": "01012345678"}, "past_history": "x", "diagnosis": "y"})
check("receptionist: patient saved, clinical parts skipped", rc.status_code == 201 and set(rc.json()["skipped"]) == {"past_history", "visit"}, rc.text)
e = c.get("/api/patients/" + p["id"], headers=D).json(); check("edit keeps approximate age", c.put("/api/patients/" + p["id"], headers=D, json={"full_name": e["full_name"], "age_years": e["age_years"]}).json()["dob_approx"] == 1)
check("settings: admin only", c.get("/api/settings", headers=D).status_code == 403 and c.get("/api/settings", headers=login("admin", "Admin#12345")).json()["ai"] is False)
check("settings: bad key rejected", c.post("/api/settings/ai-key", headers=login("admin", "Admin#12345"), json={"key": "abc"}).status_code == 422)
print(f"\n{ok} passed, {fail} failed"); sys.exit(1 if fail else 0)
