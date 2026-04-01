FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY src/ src/
COPY rules/ rules/
COPY .env.example .env

EXPOSE 8000

CMD ["uvicorn", "artha.app:app", "--host", "0.0.0.0", "--port", "8000"]
