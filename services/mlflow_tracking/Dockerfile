FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY services/mlflow_tracking/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY services/mlflow_tracking /app/services/mlflow_tracking
COPY scripts/mlflow_artifact_backup.py /app/scripts/mlflow_artifact_backup.py

CMD ["python", "-m", "services.mlflow_tracking.server"]
