SERVICE_NAME=stock-analytics
PYPROJECT_NAME=stock-analysis

# コンテナ内かを判定
IN_DOCKER := $(shell if [ -f /.dockerenv ] || ([ -e /proc/1/cgroup ] && grep -q 'docker' /proc/1/cgroup); then echo "yes"; else echo "no"; fi)
DOCKER_RUN := $(if $(filter yes,$(IN_DOCKER)),,docker compose exec $(SERVICE_NAME))

.PHONY: lint format update debug

lint:
	$(DOCKER_RUN) ruff check .

format:
	$(DOCKER_RUN) ruff format .

update:
	$(DOCKER_RUN) uv pip install .[dev] --system

dev:
	$(DOCKER_RUN) streamlit run src/main.py --server.fileWatcherType auto --logger.level=debug
