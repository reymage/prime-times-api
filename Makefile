.PHONY: install dev migrate upgrade docker-build docker-up docker-down docker-logs clean

install:
	pip install -r requirements.txt

dev:
	uvicorn app.main:app --reload --port 8000

# Aerich migration commands
aerich-init:
	aerich init-db

migrate:
	aerich migrate

upgrade:
	aerich upgrade

# Docker
docker-build:
	docker compose build

docker-up:
	docker compose up -d

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f app

docker-reset:
	docker compose down -v

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
