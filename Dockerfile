FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AIDA_SERVICES_GATEWAY_HOST=0.0.0.0 \
    AIDA_SERVICES_GATEWAY_PORT=8000 \
    AIDA_GATEWAY_SESSION_DB=/home/aida/state/sessions.sqlite3

WORKDIR /app

COPY requirements-gateway.txt ./requirements-gateway.txt
RUN pip install --no-cache-dir -r requirements-gateway.txt

RUN useradd --create-home --uid 10001 aida && mkdir -p /home/aida/state && chown aida:aida /home/aida/state
COPY --chown=aida:aida aida ./aida
USER aida
VOLUME ["/home/aida/state"]
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" || exit 1

EXPOSE 8000

CMD ["python", "-m", "aida.services_gateway"]
