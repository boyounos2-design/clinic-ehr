"""Unit tests for the sheet parser:  python test_intake.py"""
import sys; sys.path.insert(0, "app")
from datetime import date, timedelta
from intake import extract_fields, normalise_ai
ok = fail = 0
def check(name, got, want):
    global ok, fail
    good = got == want; ok, fail = (ok + 1, fail) if good else (ok, fail + 1)
    print(("PASS " if good else "FAIL ") + name, "" if good else f"\n   got={got!r}\n  want={want!r}")

AR = """الاسم: أحمد محمد علي
السن: ٣٥ سنة
النوع: ذكر
التليفون: ٠١٠٠١٢٣٤٥٦٧
العنوان: أرمنت الحيط - الأقصر
التاريخ المرضي: سكر وضغط
كسر سابق في الساعد الأيمن
الشكوى: ألم في الركبة اليمنى بعد إصابة رياضية
الفحص: Lachman +ve
anterior drawer +ve
التشخيص: تمزق الرباط الصليبي الأمامي
العلاج: جراحة منظار + علاج طبيعي
المتابعة: بعد أسبوعين"""
r = extract_fields(AR); f, c = r["fields"], r["confidence"]
check("ar name", f["full_name"], "أحمد محمد علي")
check("ar age (arabic digits)", f["age"], 35)
check("ar gender", f["gender"], "male")
check("ar phone", f["phone"], "01001234567")
check("ar address keeps dash", f["address"], "أرمنت الحيط - الأقصر")
check("ar multiline history", f["past_history"], "سكر وضغط\nكسر سابق في الساعد الأيمن")
check("ar multiline exam", f["examination"], "Lachman +ve\nanterior drawer +ve")
check("ar diagnosis", f["diagnosis"], "تمزق الرباط الصليبي الأمامي")
check("ar plan", f["management_plan"], "جراحة منظار + علاج طبيعي")
check("ar relative follow-up", f["follow_up"], (date.today() + timedelta(days=14)).isoformat())
check("labeled fields are high confidence", c["full_name"], "high")

EN = """Name: Mona Hassan   
Age: 32 y
Sex: F
Mobile: +20 122 765 4321
Address: Luxor, Egypt
PMH: DM type 2
C/O: pain left wrist after fall
O/E: tender distal radius
Dx: distal radius fracture
Rx: cast 6 weeks
F/U: 12/11/2026"""
r = extract_fields(EN); f = r["fields"]
check("en name", f["full_name"], "Mona Hassan")
check("en age", f["age"], 32); check("en gender", f["gender"], "female")
check("en intl phone", f["phone"], "01227654321")
check("en history/complaint", (f["past_history"], f["chief_complaint"]), ("DM type 2", "pain left wrist after fall"))
check("en exam/dx/plan", (f["examination"], f["diagnosis"], f["management_plan"]), ("tender distal radius", "distal radius fracture", "cast 6 weeks"))
check("en day-first date", f["follow_up"], "2026-11-12")

NOLABEL = "سارة إبراهيم\n01155577889\nانثى 28 سنة\nألم في الكتف"
r = extract_fields(NOLABEL); f, c = r["fields"], r["confidence"]
check("unlabeled: name guessed, low confidence", (f["full_name"], c["full_name"]), ("سارة إبراهيم", "low"))
check("unlabeled: phone/gender/age", (f["phone"], f["gender"], f["age"]), ("01155577889", "female", 28))
check("unlabeled: leftover goes to notes", f["physician_notes"], "ألم في الكتف")

check("empty sheet", extract_fields("")["fields"]["full_name"], None)
check("name in value is not mistaken for label ('ph' inside a word)", extract_fields("Photo taken today")["fields"]["past_history"], None)
a = normalise_ai({"full_name": "علي", "age": "40", "phone": "٠١٠٠٠٠٠٠٠٠٠", "gender": "ذكر", "dob": "12/03/1985", "uncertain": ["phone"]})
check("ai normalise", (a["fields"]["age"], a["fields"]["gender"], a["fields"]["dob"], a["confidence"]["phone"]), (40, "male", "1985-03-12", "low"))

# ---- AI engine against a fake Anthropic server (no key / no network needed) ----
import os, json, httpx, tempfile, pathlib
from PIL import Image
import intake as I
os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-key-000000000000"
tmp = pathlib.Path(tempfile.mkdtemp()) / "sheet.png"; Image.new("RGB", (400, 300), "white").save(tmp)
seen = {}
def handler(req):
    seen["h"] = dict(req.headers); seen["b"] = json.loads(req.content)
    return httpx.Response(200, json={"content": [{"type": "text", "text": "```json\n" + json.dumps({"full_name": "خالد سعيد", "age": 41, "gender": "male", "phone": "01011112222", "diagnosis": "كسر الظنبوب", "follow_up": "2026-11-01", "uncertain": ["diagnosis"]}) + "\n```"}]})
res = I.ai_extract(tmp, "image/png", client=httpx.Client(transport=httpx.MockTransport(handler)))
check("ai: request carries key + image + prompt", (seen["h"]["x-api-key"], seen["b"]["messages"][0]["content"][0]["type"], "never invent" in seen["b"]["messages"][0]["content"][1]["text"]), ("sk-ant-test-key-000000000000", "image", True))
check("ai: fields parsed from fenced JSON", (res["fields"]["full_name"], res["fields"]["age"], res["fields"]["follow_up"]), ("خالد سعيد", 41, "2026-11-01"))
check("ai: uncertain -> low confidence", (res["confidence"]["diagnosis"], res["confidence"]["full_name"]), ("low", "high"))
bad = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401, text="invalid x-api-key")))
try: I.ai_extract(tmp, "image/png", client=bad); msg = ""
except RuntimeError as e: msg = str(e)
check("ai: HTTP error becomes a readable message", "401" in msg, True)
print(f"\n{ok} passed, {fail} failed"); sys.exit(1 if fail else 0)
