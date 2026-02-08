BACKEND_HOST ?= 0.0.0.0
BACKEND_PORT ?= 8000
PYTEST ?= $(if $(wildcard .venv/bin/pytest),.venv/bin/pytest,pytest)

.PHONY: backend-dev backend-test ui-test ui-test-headed ui-test-live ui-artifacts ui-sessions ui-gate collector-build skills-validate skills-score skills-score-all

backend-dev:
	uvicorn app.main:app --app-dir backend --host $(BACKEND_HOST) --port $(BACKEND_PORT) --reload

backend-test:
	$(PYTEST) -q backend/tests

ui-test:
	npm --prefix ui-tests test -- --config=playwright.config.js

ui-test-headed:
	PLAYWRIGHT_HEADLESS=0 npm --prefix ui-tests test -- --config=playwright.config.js

# Requires backend running separately (for live log visibility in that terminal).
ui-test-live:
	UI_TEST_REUSE_SERVER=1 PLAYWRIGHT_HEADLESS=0 npm --prefix ui-tests test -- --config=playwright.config.js

ui-artifacts:
	python scripts/ui_artifacts_summary.py

ui-sessions:
	python scripts/ui_telemetry_sessions.py

ui-gate:
	rm -f artifacts/ui/telemetry/latest-gate-session.txt
	npm --prefix ui-tests test -- --config=playwright.config.js
	python scripts/ui_artifacts_summary.py --required-kinds-file ui-tests/telemetry-gate.json --session-id-file artifacts/ui/telemetry/latest-gate-session.txt

collector-build:
	cargo build --manifest-path collector/Cargo.toml --release --target x86_64-pc-windows-gnu

skills-validate:
	python scripts/validate_skill_assets.py

SKILL_CASES ?=
SKILL_RESULTS ?=
SKILL_CASES_ROOT ?= evals/skills
SKILL_RESULTS_ROOT ?= evals/results/skills

skills-score:
	@test -n "$(SKILL_CASES)" || (echo "Set SKILL_CASES=evals/skills/<skill>/cases.json" && exit 2)
	@test -n "$(SKILL_RESULTS)" || (echo "Set SKILL_RESULTS=<results.json>" && exit 2)
	python scripts/score_skill_evals.py --cases "$(SKILL_CASES)" --results "$(SKILL_RESULTS)"

skills-score-all:
	python scripts/score_all_skill_evals.py --cases-root "$(SKILL_CASES_ROOT)" --results-root "$(SKILL_RESULTS_ROOT)"
