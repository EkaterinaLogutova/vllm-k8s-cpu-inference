#!/bin/sh
set -eu

require_env() {
  name="$1"
  eval "value=\${$name:-}"
  if [ -z "$value" ]; then
    echo "fatal: required environment variable $name is empty" >&2
    exit 64
  fi
}

require_env API_TOKEN
require_env MODEL_MOUNT
require_env MODEL_SUBDIR
require_env SERVED_MODEL_NAME

MODEL_PATH="${MODEL_MOUNT%/}/${MODEL_SUBDIR}"
MARKER="$MODEL_PATH/.download-complete.json"

if [ ! -f "$MARKER" ] || [ ! -f "$MODEL_PATH/config.json" ]; then
  echo "fatal: model is not ready at $MODEL_PATH; initContainer must finish first" >&2
  exit 66
fi

PORT="${PORT:-8000}"
DTYPE="${DTYPE:-bfloat16}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-2048}"
MAX_NUM_SEQS="${MAX_NUM_SEQS:-8}"
MAX_NUM_BATCHED_TOKENS="${MAX_NUM_BATCHED_TOKENS:-2048}"

echo "starting vLLM model=${SERVED_MODEL_NAME} port=${PORT} dtype=${DTYPE}" >&2

exec vllm serve "$MODEL_PATH" \
  --served-model-name "$SERVED_MODEL_NAME" \
  --host 0.0.0.0 \
  --port "$PORT" \
  --dtype "$DTYPE" \
  --max-model-len "$MAX_MODEL_LEN" \
  --max-num-seqs "$MAX_NUM_SEQS" \
  --max-num-batched-tokens "$MAX_NUM_BATCHED_TOKENS" \
  --enable-chunked-prefill \
  --enable-prefix-caching \
  --no-enable-log-requests \
  --no-enable-log-outputs \
  --api-key "$API_TOKEN" \
  --middleware privacy_middleware.PrivacyAndAuthMiddleware \
  --enable-request-id-headers \
  --disable-fastapi-docs \
  --disable-access-log-for-endpoints /health,/metrics,/version \
  --uvicorn-log-level info

