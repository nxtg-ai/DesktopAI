BACKEND_HOST ?= 0.0.0.0
BACKEND_PORT ?= 8000
VENV_BIN := $(if $(wildcard .venv/bin/python),.venv/bin/,)
PYTEST ?= $(VENV_BIN)pytest
PYTHON ?= $(VENV_BIN)python

.PHONY: backend-dev backend-test backend-test-integration backend-lint backend-typecheck ui-test ui-test-headed ui-test-live ui-artifacts ui-sessions ui-gate collector-build collector-lint skills-validate skills-score skills-score-all

backend-dev:
	$(VENV_BIN)uvicorn app.main:app --app-dir backend --host $(BACKEND_HOST) --port $(BACKEND_PORT) --reload

backend-test:
	$(PYTEST) -q backend/tests -m "not integration"

backend-test-integration:
	$(PYTEST) -v backend/tests/test_llm_integration.py -m integration --timeout=120

backend-lint:
	$(VENV_BIN)ruff check backend/app/ backend/tests/

backend-typecheck:
	$(VENV_BIN)pyright backend/app/

collector-build:
	cargo build --manifest-path collector/Cargo.toml --release --target x86_64-pc-windows-gnu

collector-lint:
	cd collector && cargo clippy --all-targets -- -D warnings

collector-test:
	cd collector && cargo test --lib

ui-test:
	npm --prefix ui-tests test -- --config=playwright.config.js

ui-test-headed:
	PLAYWRIGHT_HEADLESS=0 npm --prefix ui-tests test -- --config=playwright.config.js

# Requires backend running separately (for live log visibility in that terminal).
ui-test-live:
	UI_TEST_REUSE_SERVER=1 PLAYWRIGHT_HEADLESS=0 npm --prefix ui-tests test -- --config=playwright.config.js

ui-artifacts:
	$(PYTHON) scripts/ui_artifacts_summary.py

ui-sessions:
	$(PYTHON) scripts/ui_telemetry_sessions.py

ui-gate:
	rm -f artifacts/ui/telemetry/latest-gate-session.txt
	npm --prefix ui-tests test -- --config=playwright.config.js
	$(PYTHON) scripts/ui_artifacts_summary.py --required-kinds-file ui-tests/telemetry-gate.json --session-id-file artifacts/ui/telemetry/latest-gate-session.txt

skills-validate:
	$(PYTHON) scripts/validate_skill_assets.py

SKILL_CASES ?=
SKILL_RESULTS ?=
SKILL_CASES_ROOT ?= evals/skills
SKILL_RESULTS_ROOT ?= evals/results/skills

skills-score:
	@test -n "$(SKILL_CASES)" || (echo "Set SKILL_CASES=evals/skills/<skill>/cases.json" && exit 2)
	@test -n "$(SKILL_RESULTS)" || (echo "Set SKILL_RESULTS=<results.json>" && exit 2)
	$(PYTHON) scripts/score_skill_evals.py --cases "$(SKILL_CASES)" --results "$(SKILL_RESULTS)"

skills-score-all:
	$(PYTHON) scripts/score_all_skill_evals.py --cases-root "$(SKILL_CASES_ROOT)" --results-root "$(SKILL_RESULTS_ROOT)"
