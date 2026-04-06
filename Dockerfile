FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server ./server
COPY static ./static

ENV PYTHONUNBUFFERED=1
# Set in Railway: ANTHROPIC_API_KEY (Claude API for driver safety reasoning)
ENV ANTHROPIC_API_KEY=
EXPOSE 8000

CMD ["sh", "-c", "uvicorn server.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
