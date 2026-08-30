.PHONY: help up down dev test lint format migrate revision clean

help:
	@echo "RAGForge Management Commands:"
	@echo "  make up        - Start Docker Compose containers"
	@echo "  make down      - Stop Docker Compose containers"
	@echo "  make dev       - Start local Uvicorn dev server"
	@echo "  make test      - Run pytest suite"
	@echo "  make lint      - Run Ruff linter"
	@echo "  make format    - Run Ruff formatter"
	@echo "  make migrate   - Apply Alembic migrations"
	@echo "  make clean     - Remove Python cache files"

up:
	docker compose up --build -d

down:
	docker compose down

dev:
	cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

test:
	cd backend && pytest -v

lint:
	cd backend && ruff check .

format:
	cd backend && ruff format .

migrate:
	cd backend && alembic upgrade head

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
