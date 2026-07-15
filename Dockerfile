FROM python:3.13-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir poetry==2.2.1
WORKDIR /app

COPY pyproject.toml poetry.lock ./

RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi --only main --no-root

# Pré-télécharge le tokenizer pour qu'il soit en cache dans l'image
RUN python -c "from tokenizers import Tokenizer; Tokenizer.from_pretrained('mistralai/Mixtral-8x7B-v0.1')"

COPY src/ ./src/
RUN mkdir -p data

EXPOSE 8501 8502
CMD ["streamlit", "run", "src/app.py", "--server.port=8501", "--server.address=0.0.0.0"]