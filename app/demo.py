"""Optional: add two sample patients so you can try the screens.   python app/demo.py"""
import main
from main import PatientIn, new_id, now, q, save_patient, add_followup, index_history, index_visit
from datetime import date, timedelta

main.init_db()
doc = q("SELECT id FROM users WHERE username='doctor'", one=True)["id"]
SAMPLES = [
    ("أحمد محمد علي", date(1985, 3, 12), "01001234567", "أرمنت الحيط، الأقصر", "male", "كسر في عظمة الظنبوب",
     "ألم في الركبة اليمنى بعد إصابة رياضية", "تمزق في الرباط الصليبي الأمامي", "Positive Lachman, anterior drawer", "ACL tear",
     "Arthroscopic ACL reconstruction; physiotherapy"),
    ("Mona Hassan", date(1992, 7, 30), "01227654321", "Luxor, Egypt", "female", "Diabetes mellitus type 2",
     "Pain in the left wrist after a fall", "Tenderness over distal radius", "Distal radius fracture", "S52.5",
     "Cast for 6 weeks, calcium and vitamin D"),
]
for name, dob, ph, addr, g, pmh, cc, sym, exam, dx, plan in SAMPLES:
    pid = new_id()
    save_patient(pid, PatientIn(full_name=name, date_of_birth=dob, phone=ph, address=addr, gender=g), doc, create=True)
    hid = new_id()
    q("INSERT INTO patient_history(id,patient_id,kind,description,created_by,created_at) VALUES (?,?,?,?,?,?)", (hid, pid, "medical", pmh, doc, now()))
    index_history(hid)
    vid = new_id()
    q("""INSERT INTO visits(id,patient_id,visit_date,chief_complaint,symptoms,examination,diagnosis,management_plan,doctor_id,created_at,updated_at)
         VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (vid, pid, now(), cc, sym, exam, dx, plan, doc, now(), now()))
    q("INSERT INTO prescriptions(id,visit_id,drug_name,dose,frequency,duration) VALUES (?,?,?,?,?,?)", (new_id(), vid, "Celecoxib", "200 mg", "once daily", "7 days"))
    index_visit(vid)
    add_followup(pid, vid, date.today() + timedelta(days=7), "Review after treatment start")
print("Demo patients added.")
