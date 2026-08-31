# Makefile for Project Rebuild Docker operations
.PHONY: help build up down test compile shell clean logs

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Available targets:'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-15s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

build: ## Build Docker images
	docker-compose build

up: ## Start blockchain node
	docker-compose up -d contracts

down: ## Stop all services
	docker-compose down

test: ## Run tests
	docker-compose run --rm test

test-verbose: ## Run tests with verbose output
	docker-compose run --rm test forge test -vvv

compile: ## Compile contracts
	docker-compose run --rm compile

shell: ## Open shell in dev container
	docker-compose run --rm dev /bin/bash

dev: ## Start development environment
	docker-compose --profile dev up -d dev

logs: ## View logs
	docker-compose logs -f

clean: ## Clean up containers and volumes
	docker-compose down -v
	docker system prune -f

rebuild: ## Rebuild images without cache
	docker-compose build --no-cache

install-deps: ## Install Foundry dependencies
	docker-compose run --rm dev forge install OpenZeppelin/openzeppelin-contracts --no-commit
	docker-compose run --rm dev forge install smartcontractkit/chainlink-brownie-contracts --no-commit

format: ## Format code
	docker-compose run --rm dev forge fmt

coverage: ## Run coverage
	docker-compose run --rm test forge coverage

