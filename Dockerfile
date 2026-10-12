FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 EHR_DATA_DIR=/data EHR_ENV=production
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-ara tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY frontend ./frontend
RUN useradd -r -u 10001 ehr && mkdir /data && chown ehr /data
USER ehr
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')" || exit 1
# one worker: the app keeps a SQLite write lock in-process
CMD ["uvicorn", "main:app", "--app-dir", "app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
