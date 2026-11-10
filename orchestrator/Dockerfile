# D2D orchestrator: the only container with the Docker socket. Manages per-person workspace instances.
FROM python:3.12-slim
RUN pip install --no-cache-dir fastapi==0.115.6 uvicorn==0.32.1 httpx==0.28.1
WORKDIR /srv
COPY orchestrator/server.py .
EXPOSE 8095
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8095/health')"
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8095"]
