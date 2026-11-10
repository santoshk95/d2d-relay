#!/bin/sh
set -e
# LiteLLM loads custom_auth modules next to its config file, so the config is linked into /app beside d2d_auth.py.
# Until the web app has written a config (no routes yet), start with an empty model list.
if [ ! -f /data/llm/config.yaml ]; then
  printf 'model_list: []\ngeneral_settings:\n  custom_auth: d2d_auth.user_api_key_auth\n' > /tmp/empty.yaml
  ln -sf /tmp/empty.yaml /app/config.yaml
else
  ln -sf /data/llm/config.yaml /app/config.yaml
fi
# LiteLLM refuses to run without a master key. D2D never uses one (only its signed run keys, d2d_auth.py), so a fresh
# random key is made at every start and never stored or shown anywhere.
export LITELLM_MASTER_KEY="sk-$(python -c 'import secrets; print(secrets.token_hex(32))')"
exec litellm --config /app/config.yaml --host 0.0.0.0 --port 4000
