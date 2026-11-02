# One image, two processes: the compose file runs it twice, once as the
# RSS feed (app.py) and once as the control panel (gui.py).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RSS_CONFIG_FILE=/data/config.json \
    RSS_LOG_FILE=/data/rss_changes.log \
    FEED_PORT=5050 \
    GUI_PORT=5001

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py ./

# config.json and the activity log live here, shared by both services.
VOLUME ["/data"]
EXPOSE 5050 5001

CMD ["python", "gui.py"]
