FROM python:3.12-slim
RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY crm.py llm.py ./
USER app
EXPOSE 8000
