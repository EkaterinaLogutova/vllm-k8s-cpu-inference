# syntax=docker/dockerfile:1.7
ARG VLLM_VERSION=0.27.0
FROM vllm/vllm-openai-cpu:v${VLLM_VERSION}-x86_64

USER root

RUN groupadd --gid 10001 vllmapp \
    && useradd --uid 10001 --gid 10001 --create-home --home-dir /home/vllmapp \
       --shell /usr/sbin/nologin vllmapp \
    && install -d -o 10001 -g 10001 /opt/vllm-custom

COPY --chown=10001:10001 app/privacy_middleware.py /opt/vllm-custom/privacy_middleware.py
COPY --chown=10001:10001 app/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY requirements.txt /opt/vllm-custom/requirements.txt

RUN chmod 0555 /usr/local/bin/entrypoint.sh \
    && python3 -c "import importlib.metadata as m; expected='0.27.0'; actual=m.version('vllm'); assert actual == expected, f'vLLM {actual} != {expected}'"

ENV PYTHONPATH=/opt/vllm-custom \
    HOME=/tmp \
    XDG_CACHE_HOME=/tmp/.cache \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    VLLM_LOGGING_LEVEL=INFO \
    VLLM_REQUEST_BODY_LOG_LEVEL=CRITICAL \
    PYTHONUNBUFFERED=1

USER 10001:10001
EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

