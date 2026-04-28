FROM python:3.13-slim

ENV APP_HOME /app
ENV PYTHONPATH ${APP_HOME}
WORKDIR ${APP_HOME}

# Claude Code CLI のインストール
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates nodejs npm && \
    npm install -g @anthropic-ai/claude-code && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ${APP_HOME}/

RUN pip install --upgrade pip && \
    pip install uv

RUN uv pip install . --system

COPY src ${APP_HOME}/src

ENV PYTHONPATH "${PYTHONPATH}:${APP_HOME}/src"

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8102"]

