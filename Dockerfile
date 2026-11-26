# Production image for the AG-101 Agent Spend Monitor (standard-library HTTP server + static ui/).
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY . /app
EXPOSE 8000
CMD ["sh", "/app/deploy/start.sh"]
