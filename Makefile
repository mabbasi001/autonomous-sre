COMPOSE := docker compose -f deploy/compose/docker-compose.yml

.PHONY: db db-stop migrate api worker test lint

db:
	$(COMPOSE) up -d --wait postgres

db-stop:
	$(COMPOSE) stop postgres

migrate:
	cd backend && uv run alembic upgrade head

api:
	cd backend && uv run uvicorn app.main:app --reload --port 8000

worker:
	cd backend && uv run python -m app.worker

test:
	cd backend && uv run pytest
	cd agent && go test ./...

lint:
	cd backend && uv run ruff check .
	cd agent && go vet ./...
