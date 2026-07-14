FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data \
    && chown app:app /data
USER app
EXPOSE 8080

CMD ["uvicorn", "viking_forge.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
