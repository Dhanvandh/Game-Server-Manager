# Bookworm = stable Debian; avoids `python:3.12-slim` tracking testing (trixie) and mirror 403 issues.
# psycopg[binary] + bcrypt ship wheels — no gcc/libpq-dev needed for normal amd64/arm64 builds.
FROM python:3.12-slim-bookworm

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

ENV FLASK_APP=run.py
ENV PYTHONUNBUFFERED=1

EXPOSE 5000

CMD ["gunicorn", "--worker-class", "eventlet", "-w", "1", "-b", "0.0.0.0:5000", "run:app"]
