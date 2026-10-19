FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    PORT=8000

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py auth_security.py assistant_engine.py voice_gateway.py bokharest_ordering.py bokharest_demo.py ./
COPY templates/ ./templates/
COPY static/ ./static/
COPY data/README.txt ./data/README.txt

# The app writes its SQLite demo database here unless DATABASE_PATH is specified.
# Mount a persistent volume at /app/data before using the service for real orders.
RUN mkdir -p /app/data

EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers"]
