BACKEND_HOST ?= 0.0.0.0
BACKEND_PORT ?= 8000

.PHONY: backend-dev backend-test collector-build

backend-dev:
	uvicorn app.main:app --app-dir backend --host $(BACKEND_HOST) --port $(BACKEND_PORT) --reload

backend-test:
	pytest -q backend/tests

collector-build:
	cargo build --manifest-path collector/Cargo.toml --release --target x86_64-pc-windows-gnu
