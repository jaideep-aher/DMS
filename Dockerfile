FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server ./server
COPY static ./static

ENV PYTHONUNBUFFERED=1
# Set in Railway: OPENAI_API_KEY (OpenAI API for driver safety reasoning)
# Optional: OPENAI_MODEL=gpt-4o-mini (default)
ENV OPENAI_API_KEY=
ENV OPENAI_MODEL=gpt-4o-mini
EXPOSE 8000

CMD ["sh", "-c", "uvicorn server.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
