FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 PORT=8000 DATABASE_PATH=/data/chatbot.sqlite3
WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY knowledge_base ./knowledge_base
COPY widget ./widget
COPY demo ./demo

RUN useradd --create-home bot && mkdir -p /data && chown bot /data
USER bot
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"

# ANTHROPIC_API_KEY and the other settings come from the host's environment, never the image.
CMD ["sh", "-c", "uvicorn app.main:_lazy_app --factory --host $HOST --port $PORT --proxy-headers"]
