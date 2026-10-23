ARG VLLM_VERSION=0.27.0
FROM vllm/vllm-openai-cpu:v${VLLM_VERSION}-x86_64@sha256:ad2d073b2ff1b755e0d0b9e33a581bfcbadde22c13a073af1dfff1d553119d38

USER root

RUN groupadd --gid 10001 vllmapp \
    && useradd --uid 10001 --gid 10001 --create-home --home-dir /home/vllmapp \
       --shell /usr/sbin/nologin vllmapp \
    && install -d -o 10001 -g 10001 /opt/vllm-custom

COPY --chown=10001:10001 app/privacy_middleware.py /opt/vllm-custom/privacy_middleware.py
COPY --chown=10001:10001 app/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY requirements.txt /opt/vllm-custom/requirements.txt
COPY scripts/verify_runtime_lock.py /opt/vllm-custom/verify_runtime_lock.py

RUN chmod 0555 /usr/local/bin/entrypoint.sh \
    && python3 /opt/vllm-custom/verify_runtime_lock.py /opt/vllm-custom/requirements.txt

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

