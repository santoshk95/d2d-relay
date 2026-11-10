#!/bin/sh
# Relay's AI gateway (LiteLLM): an Anthropic-compatible API in front of Amazon Bedrock, Azure AI Foundry and Google
# Vertex AI, on 127.0.0.1:4000 inside the container. The web app writes its config (routes, credentials, signing key)
# to /data/llm; d2d_auth.py accepts only run keys the web app signed.
set -e
APP=/opt/relay/gateway-app
# LiteLLM loads custom_auth modules next to its config file, so the config is linked in beside d2d_auth.py.
if [ -f /data/llm/config.yaml ]; then
  ln -sf /data/llm/config.yaml "$APP/config.yaml"
else
  printf 'model_list: []\ngeneral_settings:\n  custom_auth: d2d_auth.user_api_key_auth\n' > "$APP/empty.yaml"
  ln -sf "$APP/empty.yaml" "$APP/config.yaml"
fi
# LiteLLM refuses to run without a master key. Relay never uses one (only its signed run keys), so a fresh random key
# is made at every start and never stored or shown.
LITELLM_MASTER_KEY="sk-$(python -c 'import secrets; print(secrets.token_hex(32))')"
export LITELLM_MASTER_KEY
cd "$APP"
exec litellm --config "$APP/config.yaml" --host 127.0.0.1 --port 4000
