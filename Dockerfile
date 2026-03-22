FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn httpx python-dotenv

COPY elevenlabs_openai_shim_streaming.py .
COPY static/ static/

EXPOSE 8881

CMD ["uvicorn", "elevenlabs_openai_shim_streaming:app", "--host", "0.0.0.0", "--port", "8881"]
