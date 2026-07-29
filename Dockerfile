FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv/app

RUN addgroup --system taskmate && adduser --system --ingroup taskmate taskmate
COPY pyproject.toml ./
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
RUN pip install --no-cache-dir .
USER taskmate

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
