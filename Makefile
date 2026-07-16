PYTHON ?= /opt/homebrew/bin/python3.13
VENV := .venv
VENV_PYTHON := $(VENV)/bin/python

.PHONY: bootstrap validate clean-venv python-info

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

validate:
	$(VENV_PYTHON) -m py_compile app/tools/export_horncad.py app/tools/webster_1d.py app/tools/aperture_directivity.py app/tools/helmholtz_2d.py app/tools/helmholtz_bem_3d.py
	$(VENV_PYTHON) -m unittest discover -s automated_tests -v
	node -e "const fs=require('fs'); const html=fs.readFileSync('app/browser/HornCAD.html','utf8'); const scripts=[...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m=>m[1]).join('\n'); new Function(scripts); console.log('js_parse_ok');"

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
