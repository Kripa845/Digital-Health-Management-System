FROM python:3.12-slim

# Prevent Python from creating .pyc files
# and make Python output appear immediately
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies required by OCR (PDFs are rendered with PyMuPDF,
# so Poppler is not needed)
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# libmagic is installed above, so uploaded files' real types are checked with python-magic.
ENV LAB_USE_LIBMAGIC=True

# Hosts such as Hugging Face Spaces run the container as user 1000, so the app
# files belong to that user.
RUN useradd -m -u 1000 app && mkdir /app && chown app:app /app

# Set working directory
WORKDIR /app

# Copy requirements first for better Docker caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the backend project
COPY --chown=app:app . .

# Admin page CSS/JS, served by WhiteNoise. Needs no secrets: settings default to DEBUG at build time.
RUN python manage.py collectstatic --noinput

USER app

# Create/update the database tables on every start, then serve.
# Several workers so one long OCR upload does not block everyone else, and a
# timeout that leaves room for the capped OCR work in a request. Each worker
# loads the symptom model (~1 GB of RAM), so keep WEB_CONCURRENCY within the
# host's memory.
CMD ["sh", "-c", "python manage.py migrate --noinput && gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-10000} --workers ${WEB_CONCURRENCY:-3} --timeout ${GUNICORN_TIMEOUT:-120}"]
