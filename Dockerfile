FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY c0ontenter ./c0ontenter
COPY migrations ./migrations
COPY alembic.ini ./
RUN pip install .

CMD ["sh", "-c", "alembic upgrade head && python -m c0ontenter.main"]
