FROM python:3.12-slim

# Bundle a static ffprobe so the detail popup can read real resolution /
# bitrate / codecs.
COPY --from=mwader/static-ffmpeg:7.1 /ffprobe /usr/local/bin/ffprobe

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY templates/ templates/
COPY static/ static/

EXPOSE 5432

CMD ["python", "app.py"]
