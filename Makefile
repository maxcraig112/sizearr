PYTHON ?= python3
PIP ?= $(PYTHON) -m pip

.PHONY: help install run

help:
	@echo "Targets:"
	@echo "  install  Install Python dependencies from requirements.txt"
	@echo "  run      Start the Flask app (override paths with MOVIES_PATH / TV_PATH)"

install:
	$(PIP) install -r requirements.txt

run:
	$(PYTHON) app.py
