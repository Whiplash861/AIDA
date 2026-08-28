FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AIDA_SERVICES_GATEWAY_HOST=0.0.0.0 \
    AIDA_SERVICES_GATEWAY_PORT=8000

WORKDIR /app

COPY requirements-gateway.txt ./requirements-gateway.txt
RUN pip install --no-cache-dir -r requirements-gateway.txt

COPY aida ./aida

EXPOSE 8000

CMD ["python", "-m", "aida.services_gateway"]
