PYTHON ?= python

.PHONY: test compile verify

test:
	$(PYTHON) -m pytest

compile:
	$(PYTHON) -m compileall ai_orchestrator

verify: compile test
	@git diff --check || true
