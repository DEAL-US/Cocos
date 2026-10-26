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

# Usuario sin privilegios: el código y lo que escribe la aplicación son suyos
RUN addgroup --system app && adduser --system --ingroup app app

COPY --chown=app:app app /app


# CSS y librerías JS compilados (en desarrollo los genera el servicio frontend del compose)
COPY --chown=app:app --from=frontend /frontend/static /app/static/

# media existe antes de montar el volumen para que Docker lo cree con este dueño y no como root
RUN mkdir -p /app/media && chown app:app /app /app/media

USER app