#!/bin/sh

export OPENCLAW_GATEWAY_TOKEN=$(cat /run/secrets/openclaw_gateway_token)

while true; do
  openclaw node run \
    --host "${OPENCLAW_GATEWAY_HOST:-sam.tail88dba.ts.net}" \
    --port "${OPENCLAW_GATEWAY_PORT:-443}" \
    --tls \
    --display-name "${OPENCLAW_NODE_DISPLAY_NAME:-Willflix}"
  echo "openclaw node exited ($?), retrying in 15s..."
  sleep 15
done
