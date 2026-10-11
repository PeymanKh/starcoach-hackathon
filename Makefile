COMPOSE = docker compose -f docker-compose.dev.yml

.PHONY: install lint format typecheck test check worker \
        up down reset ps logs migrate makemigrations run superuser shell docker-build

# Install everything from uv.lock into .venv.
install:
	uv sync

# Find problems without changing files.
lint:
	uv run ruff check
	uv run ruff format --check

# Fix what can be fixed automatically.
format:
	uv run ruff check --fix
	uv run ruff format

typecheck:
	uv run pyright

test:
	uv run pytest

worker:
	uv run celery -A config worker -l info -P solo


# Django
migrate:
	uv run python manage.py migrate

makemigrations:
	uv run python manage.py makemigrations

run:
	uv run python manage.py runserver

shell:
	uv run python manage.py shell


# Infrastructure
up:
	$(COMPOSE) up -d --wait

down:  ## stop containers, KEEP the data
	$(COMPOSE) down

reset:  ## stop containers and DELETE all data
	$(COMPOSE) down -v

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f

# Everything CI runs, in the same order.
check: lint typecheck test
