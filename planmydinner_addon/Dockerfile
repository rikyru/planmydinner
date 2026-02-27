FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

COPY requirements.txt ./
# JRE opzionale: decommentare per abilitare import PDF via tabula-py
# RUN apt-get update && apt-get install -y default-jre && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/planmydinner_addon

WORKDIR /app

EXPOSE 8000

CMD ["uvicorn", "planmydinner_addon.main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
