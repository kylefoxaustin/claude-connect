.PHONY: install run dev test clean install-native native install-desktop

PORT ?= 8765
HOST ?= 127.0.0.1
NATIVE_VENV ?= .venv-native

install:
	pip install -e ".[dev]"

run:
	uvicorn conductor.main:app --host $(HOST) --port $(PORT)

dev:
	uvicorn conductor.main:app --host $(HOST) --port $(PORT) --reload

test:
	pytest -q

clean:
	rm -rf build dist *.egg-info .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} +

# --- Native App Edition (pywebview / WebKitGTK) -----------------------------
# Needs system WebKitGTK first (Ubuntu):
#   sudo apt install python3-gi gir1.2-webkit2-4.0 libwebkit2gtk-4.0-37
# The venv is created with --system-site-packages so it can see the system
# PyGObject (gi) + WebKit2 typelib, which are not pip-installable here.
install-native:
	python3 -m venv --system-site-packages $(NATIVE_VENV)
	$(NATIVE_VENV)/bin/pip install --upgrade pip setuptools
	$(NATIVE_VENV)/bin/pip install -e . pywebview
	@$(NATIVE_VENV)/bin/python -c "import gi; gi.require_version('WebKit2','4.0'); from gi.repository import WebKit2; print('WebKitGTK OK')" \
		|| (echo 'ERROR: system WebKitGTK missing — run the apt install above'; exit 1)

native:
	$(NATIVE_VENV)/bin/python app.py

# Install a desktop launcher into the user's app menu, with absolute paths
# substituted for this checkout. Re-run if you move the repo.
install-desktop:
	@mkdir -p $(HOME)/.local/share/applications
	@sed -e 's|@PYTHON@|$(CURDIR)/$(NATIVE_VENV)/bin/python|g' \
	     -e 's|@APPDIR@|$(CURDIR)|g' \
	     packaging/conductor.desktop.in > $(HOME)/.local/share/applications/conductor.desktop
	@update-desktop-database $(HOME)/.local/share/applications 2>/dev/null || true
	@echo "Installed -> $(HOME)/.local/share/applications/conductor.desktop"
