FROM python:3.13-slim

ENV APP_HOME /app
ENV PYTHONPATH ${APP_HOME}
WORKDIR ${APP_HOME}

COPY pyproject.toml ${APP_HOME}/

RUN pip install --upgrade pip && \
    pip install uv

RUN uv pip install . --system

COPY src ${APP_HOME}/src

ENV PYTHONPATH "${PYTHONPATH}:${APP_HOME}/src"

CMD ["streamlit", "run", "src.main.py"]
