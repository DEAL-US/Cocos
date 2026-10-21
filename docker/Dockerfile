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


COPY --from=frontend /frontend/static /app/static/

# Guardar el CSS y las librerías JS fuera de /app para que el volumen no los oculte. Odio TailWind
RUN mkdir -p /opt/frontend && \
    cp /app/static/css/tailwind.css /opt/frontend/tailwind.css && \
    cp -r /app/static/vendor /opt/frontend/vendor


# Non-root user for security
RUN addgroup --system app && adduser --system --ingroup app app
RUN chown -R app:app /app