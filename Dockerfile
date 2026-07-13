ARG PYTHON_IMAGE=python:3.12.13-alpine3.24@sha256:6d43704baacd1bfbe7c295d7f13079d5d8104ed33568873133f8fc69980419df

FROM ${PYTHON_IMAGE} AS dependencies

WORKDIR /build

COPY requirements/runtime.lock ./requirements/runtime.lock

RUN python -m pip install \
      --disable-pip-version-check \
      --no-cache-dir \
      --no-compile \
      --require-hashes \
      --root-user-action=ignore \
      --prefix=/install \
      -r requirements/runtime.lock \
    && PYTHONPATH=/install/lib/python3.12/site-packages python -m pip check

FROM ${PYTHON_IMAGE} AS runtime

WORKDIR /app

COPY --from=dependencies /install /usr/local
COPY deploy/marketing-agent-entrypoint.sh /usr/local/bin/marketing-agent-entrypoint
COPY src ./src
COPY config ./config
COPY Kampagnen ./Kampagnen
COPY Zielgruppen ./Zielgruppen
COPY deploy/n8n/workflows ./deploy/n8n/workflows

RUN apk add --no-cache su-exec=0.3-r0 \
    && addgroup -S -g 10001 marketing \
    && adduser -S -D -H -u 10001 -G marketing -h /nonexistent -s /sbin/nologin marketing \
    && mkdir -p /data \
    && chown marketing:marketing /data \
    && chmod 0755 /usr/local/bin/marketing-agent-entrypoint

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3).read()"]

ENTRYPOINT ["/usr/local/bin/marketing-agent-entrypoint"]
CMD ["uvicorn", "marketing_machine.api:app", "--host", "0.0.0.0", "--port", "8080", "--no-proxy-headers"]
