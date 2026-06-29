PYTHON ?= /opt/homebrew/bin/python3.13
VENV := .venv
VENV_PYTHON := $(VENV)/bin/python

.PHONY: bootstrap test clean-venv python-info

bootstrap:
	@if [ ! -x "$(PYTHON)" ]; then \
		echo "Python 3.13 not found at $(PYTHON)."; \
		echo "Install it with: brew install python@3.13"; \
		exit 1; \
	fi
	rm -rf $(VENV)
	$(PYTHON) -m venv $(VENV)
	$(VENV_PYTHON) -m pip install --upgrade pip setuptools wheel
	$(VENV_PYTHON) -m pip install -e '.[dev]'

test:
	$(VENV_PYTHON) -m pytest

clean-venv:
	rm -rf $(VENV)

python-info:
	@echo "Project Python:"
	@$(VENV_PYTHON) --version 2>/dev/null || true
	@echo
	@echo "System python3:"
	@command -v python3 || true
	@python3 --version || true
	@echo
	@echo "Homebrew python3.13:"
	@ls -l /opt/homebrew/bin/python3.13 2>/dev/null || true
	@/opt/homebrew/bin/python3.13 --version 2>/dev/null || true
