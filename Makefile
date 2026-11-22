COMPOSE := docker compose --profile core --profile observability

.DEFAULT_GOAL := help
.PHONY: help install up up-all down logs ps lint format typecheck test test-integration check clean

help: ## Lista os alvos
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-18s %s\n", $$1, $$2}'

install: ## Instala dependências com uv
	uv sync

up: ## Sobe Postgres, Redis e Temporal (perfil core)
	docker compose --profile core up -d --wait

up-all: ## Sobe também o Phoenix (perfil observability)
	$(COMPOSE) up -d --wait

down: ## Para os serviços (mantém volumes)
	$(COMPOSE) down

logs: ## Segue os logs
	$(COMPOSE) logs -f --tail=100

ps: ## Estado dos serviços
	$(COMPOSE) ps

lint: ## ruff (lint e formato)
	uv run ruff check .
	uv run ruff format --check .

format: ## Formata o código
	uv run ruff check --fix .
	uv run ruff format .

typecheck: ## pyright em modo strict
	uv run pyright

test: ## Testes unitários (rápidos, sem Docker)
	uv run pytest -m "not integration"

test-integration: ## Testes de integração (precisam de Docker)
	uv run pytest -m integration

check: lint typecheck test ## O mesmo que o CI roda

clean: ## Remove serviços e volumes do compose
	$(COMPOSE) down -v
