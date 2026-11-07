.PHONY: setup env local-setup local-run local-stop local-doctor local-seed local-reindex db-up db-down rabbitmq-up rabbitmq-down db-migrate db-check api-integration api ai ai-migrate ai-integration web check

setup: env
	uv sync --project services/ai --locked
	dotnet restore apps/api --locked-mode
	dotnet restore apps/api/tests/integration --locked-mode
	dotnet tool restore
	npm ci --prefix apps/web

env:
	python3 scripts/init_env.py
	set -a; . ./.env; set +a; python3 scripts/init_rabbitmq.py

local-setup: setup
	python3 scripts/local_setup.py

local-doctor:
	python3 scripts/local_doctor.py

local-run:
	python3 scripts/local_run.py

local-stop:
	docker compose stop db rabbitmq redis

local-reindex:
	python3 scripts/local_reindex.py

local-seed: export STAFF_EMAIL := $(STAFF_EMAIL)
local-seed:
	@set -a; . ./.env; set +a; export ASPNETCORE_ENVIRONMENT=Development; if [ -n "$$STAFF_EMAIL" ]; then dotnet run --project apps/api --no-launch-profile -- --seed-local --staff-email "$$STAFF_EMAIL"; else dotnet run --project apps/api --no-launch-profile -- --seed-local; fi

db-up:
	docker compose up -d --wait db

db-down:
	docker compose down

rabbitmq-up: env
	docker compose up -d --wait rabbitmq

rabbitmq-down:
	docker compose stop rabbitmq

db-migrate:
	set -a; . ./.env; set +a; python3 scripts/db/migrate.py

db-check:
	dotnet build apps/api --no-restore
	python3 apps/api/tests/integration.py

api-integration: db-check


api:
	python3 scripts/local_run.py --service api

ai:
	python3 scripts/local_run.py --service ai

ai-migrate:
	set -a; . ./.env; set +a; PYTHONPATH=services/ai uv run --project services/ai --locked python -m findie_ai.migrate

ai-integration:
	uv run --project services/ai --locked python services/ai/tests/integration.py

web:
	python3 scripts/local_run.py --service web

check:
	python3 -m unittest discover -s tests -v
	uv run --project services/ai --locked pytest services/ai/tests
	dotnet build apps/api --no-restore
	python3 apps/api/tests/smoke.py
	npm test --prefix apps/web
	npm run build --prefix apps/web
