CLINIC EHR - LOCAL EDITION (Windows)
====================================

START
  1. Unzip this folder somewhere permanent (e.g. C:\ClinicEHR). Do not run it from inside the zip.
  2. Double-click  start.bat
       - First time only: it sets itself up (1-3 minutes, needs internet once).
         If Python is missing it opens the download page: install Python 3.11+ and TICK
         "Add python.exe to PATH", then double-click start.bat again.
  3. Your browser opens http://localhost:8000  (if not, type that address yourself).
  4. Sign in:   doctor / Doctor#12345     (also: nurse / Nurse#12345, reception / Desk#12345, admin / Admin#12345)
  Close the black window to stop the app. The site only works on this PC (it is not exposed to the network).

TRY WITH SAMPLE DATA (optional)
  Double-click load_demo_data.bat once (run start.bat at least once first). Adds 2 sample patients.

BEFORE REAL PATIENT DATA
  - Change the demo passwords (top bar > Account: change your password; the admin can also add users there).
  - Back up the whole "data" folder regularly (database + uploaded files) to another drive. Everything is in there.
  - Windows disk encryption (BitLocker) is strongly recommended on a PC holding patient records.

IMPORT A PATIENT FROM A PAPER SHEET (new)
  Click "Import from sheet" (top right), choose a photo/scan of the patient's sheet (or take a photo).
  The fields are filled in for you; you REVIEW them (yellow "Check" = not read with confidence) and press Save.
  Nothing is saved until you press Save. The same patient (same name or phone) is flagged before a duplicate is created.
  Two reading modes:
    - On this PC (default): needs Tesseract (see below). Good for PRINTED sheets. Handwriting is read poorly.
    - AI mode (handwriting, Arabic or English): admin clicks "Settings" and pastes an Anthropic API key
      (https://console.anthropic.com). PRIVACY: with AI on, the photo of each sheet is sent to Anthropic for reading.
      Make sure that is acceptable for your patients' data. Clear the key to switch it off.
  TRIAL MODE - OCR.Space (free key): admin > Settings > paste the OCR.Space key (free from https://ocr.space/ocrapi).
    Reads printed AND handwritten text (Arabic/English). It returns plain text, which the app sorts into fields;
    accuracy on handwriting is not guaranteed - check every field. Free plan: files up to 1 MB (photos are shrunk automatically),
    PDFs up to 1 MB / 3 pages. PRIVACY: the sheet image is sent to OCR.Space. Use SAMPLE sheets while testing, not real patient data.
    With a key set, "Automatic" uses OCR.Space; if the service fails the app falls back to the on-PC reader.
  Later (live site): switch to the Anthropic key (below) - it reads handwriting into fields directly.
  The sheet image is kept with the patient's documents. Receptionist accounts save demographics only.
  Always check names, ages, phone numbers and doses against the sheet - automatic reading can be wrong.

SCANNED DOCUMENT TEXT (OCR) - optional
  PDFs that already contain text work immediately. For photos / scanned images, install Tesseract:
    https://github.com/UB-Mannheim/tesseract/wiki   -> download the installer,
    and on the "Additional language data" screen tick  Arabic.
  Then open the document in the app and press "Re-run OCR". No restart needed.
  Always glance at extracted text - OCR makes mistakes (you can correct it in the app; corrections are what gets searched).

PROBLEMS
  "Address already in use"  -> the app is already running in another window; close it or restart the PC.
  Nothing happens / red errors in the black window -> send me a photo of the window.
