FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# SQLite database lives here; mount a NAS folder onto /data to persist it.
ENV DATABASE_URL=sqlite:////data/comidas.db
ENV PORT=8080
VOLUME ["/data"]
EXPOSE 8080

CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:8080", "app:app"]
