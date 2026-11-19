FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 10001 flowx \
    && useradd --system --uid 10001 --gid flowx --home-dir /nonexistent --shell /usr/sbin/nologin flowx

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)" || exit 1

CMD ["uvicorn", "flowx_os.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
