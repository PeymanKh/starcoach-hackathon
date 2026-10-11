FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

COPY . .
ENV PATH="/app/.venv/bin:$PATH"
RUN DJANGO_SECRET_KEY=build-only DATABASE_URL=postgres://x python manage.py collectstatic --noinput

RUN useradd --create-home app && chown -R app /app
USER app

EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2"]