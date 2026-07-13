COMPOSE = docker compose --env-file deploy/.env -f deploy/compose.yaml

.PHONY: build up down logs ps migrate backup restore test config

build:
	$(COMPOSE) build --pull

up:
	$(COMPOSE) up -d --build postgres redis web worker scheduler

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=200 web worker scheduler

ps:
	$(COMPOSE) ps

migrate:
	$(COMPOSE) run --rm --no-deps web migrate

backup:
	$(COMPOSE) --profile maintenance run --rm backup

# Usage: make restore BACKUP=daily/20260101-020000
restore:
	@test -n "$(BACKUP)" || (echo "Set BACKUP=<tier>/<timestamp>" && exit 64)
	sh deploy/scripts/restore-stack.sh "$(BACKUP)"

test:
	cd backend && python -m pytest
	cd frontend && npm test

config:
	$(COMPOSE) config --quiet
