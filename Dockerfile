FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY migrations ./migrations
RUN useradd -r -u 10001 bot && mkdir -p /data && chown bot /data
USER bot
ENV DATABASE_PATH=/data/bullshit.sqlite3 HEARTBEAT_FILE=/tmp/bullshit.heartbeat
HEALTHCHECK --interval=60s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import os,sys,time; p=os.environ['HEARTBEAT_FILE']; sys.exit(0 if time.time()-os.path.getmtime(p)<120 else 1)"
CMD ["python", "-m", "app.main"]
