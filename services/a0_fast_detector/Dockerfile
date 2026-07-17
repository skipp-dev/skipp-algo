FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY services/a0_fast_detector/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY open_prep /app/open_prep
COPY newsstack_fmp /app/newsstack_fmp
COPY services /app/services

CMD ["python", "-m", "services.a0_fast_detector.worker"]
