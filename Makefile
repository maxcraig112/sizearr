# Pick whatever Python is on PATH. On Linux this is python3; under
# Git-for-Windows `make` (which shells out to sh) it's usually python.
# Override explicitly with `make run PYTHON=...` if needed.
PYTHON ?= $(shell command -v python3 2>/dev/null || command -v python 2>/dev/null || echo python3)
PIP ?= $(PYTHON) -m pip

# Local test library (see testdata/README.md)
MOVIES_PATH ?= testdata/movies
TV_PATH ?= testdata/tv

.PHONY: help install run run-local

help:
	@echo "Targets:"
	@echo "  install    Install Python dependencies from requirements.txt"
	@echo "  run        Start the Flask app (uses MOVIES_PATH / TV_PATH from the environment)"
	@echo "  run-local  Start the app against the bundled testdata/ fixture library"

install:
	$(PIP) install -r requirements.txt

run:
	$(PYTHON) app.py

run-local:
	MOVIES_PATH=$(MOVIES_PATH) TV_PATH=$(TV_PATH) LOG_LEVEL=DEBUG $(PYTHON) app.py
