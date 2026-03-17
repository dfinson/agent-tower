.PHONY: install lint format typecheck test run ci

install:
	uv sync
	cd frontend && npm ci

lint:
	uv run ruff check backend/
	cd frontend && npm run lint

format:
	uv run ruff format backend/

typecheck:
	uv run mypy backend/
	cd frontend && npm run typecheck

test:
	uv run pytest --cov=backend --cov-report=term-missing
	cd frontend && npm run test:coverage

run:
	cd frontend && npm run build
	uv run cpl up --tunnel

ci: lint format typecheck test
