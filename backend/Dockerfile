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

# Set working directory
WORKDIR /app

# Copy requirements first for better Docker caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the backend project
COPY . .

# Django/Gunicorn listens on Render's port
# Several workers so one long OCR upload does not block everyone else, and a
# timeout that leaves room for the capped OCR work in a request.
CMD ["sh", "-c", "gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-10000} --workers ${WEB_CONCURRENCY:-3} --timeout ${GUNICORN_TIMEOUT:-120}"]