FROM node:20-alpine AS frontend

WORKDIR /frontend

COPY app/package.json app/package-lock.json ./
RUN npm ci

COPY app/ ./
RUN npm run build


FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --upgrade pip
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app /app


# CSS y librerías JS compilados (en desarrollo los genera el servicio frontend del compose)
COPY --from=frontend /frontend/static /app/static/


# Non-root user for security
RUN addgroup --system app && adduser --system --ingroup app app
RUN chown -R app:app /app