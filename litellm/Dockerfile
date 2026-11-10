# D2D LiteLLM gateway: Anthropic-compatible API in front of Amazon Bedrock, Azure AI Foundry and Google Vertex AI.
# The web app writes the config (routes, credentials) to the d2d-llm volume; d2d_auth.py checks D2D's signed run keys.
# prisma: LiteLLM's error handler imports it to classify failures (no database is used).
FROM python:3.12-slim
RUN pip install --no-cache-dir "litellm[proxy]==1.104.8" "prisma==0.15.0" && useradd -m -u 1000 llm
WORKDIR /app
COPY litellm/d2d_auth.py litellm/start.sh /app/
RUN sed -i 's/\r$//' /app/start.sh && chmod +x /app/start.sh && chown -R llm:llm /app
USER llm
EXPOSE 4000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:4000/health/liveliness')"
CMD ["/app/start.sh"]
