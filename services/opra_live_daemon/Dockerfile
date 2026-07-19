FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY services/opra_live_daemon/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY services/opra_live_daemon /app/services/opra_live_daemon
COPY newsstack_fmp /app/newsstack_fmp
COPY scripts/smc_atomic_write.py /app/scripts/smc_atomic_write.py
COPY databento_*.py /app/

CMD ["python", "-m", "services.opra_live_daemon.main"]
