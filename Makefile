.PHONY: install run dev test clean install-native native install-desktop install-app uninstall-app

PORT ?= 8765
HOST ?= 127.0.0.1
NATIVE_VENV ?= .venv-native

# Staged-install location (overridable, mainly for testing). The app is copied
# here and the launcher points at it, so the cloned repo becomes disposable.
APP_HOME ?= $(HOME)/.local/share/conductor
APPLICATIONS_DIR ?= $(HOME)/.local/share/applications
# Runtime files copied into APP_HOME: the entrypoint, backend package, served
# frontend, icon, and the relaunch helper scripts (claude-tracked).
STAGE_ITEMS := app.py conductor frontend assets scripts packaging pyproject.toml

# Build-time setuptools for the native venv. >=64 is required for PEP 660
# editable installs (this project is pyproject-only, no setup.py). The upper cap
# avoids a noisy (but harmless) pip resolver warning on machines whose
# --system-site-packages user-site pins setuptools lower for an ML stack
# (e.g. torch<82, spsdk<81) — the venv's setuptools is isolated and only used to
# build/run Conductor, but capping keeps the install output clean.
SETUPTOOLS_REQ ?= setuptools>=64,<81

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
	$(NATIVE_VENV)/bin/pip install --upgrade pip "$(SETUPTOOLS_REQ)"
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

# Staged desktop install: copy the app into a stable home ($(APP_HOME)), build
# the native venv THERE, and point the launcher at it — so the cloned repo is
# disposable afterwards. Needs the system WebKitGTK (same apt deps as above).
# Re-run to update; 'make uninstall-app' to remove. Override APP_HOME to test.
install-app:
	@echo ">> Staging Conductor into $(APP_HOME)"
	@mkdir -p $(APP_HOME)
	@cp -r $(STAGE_ITEMS) $(APP_HOME)/
	@chmod +x $(APP_HOME)/scripts/* 2>/dev/null || true
	@# Carry settings over: keep a staged one if present, else this clone's, else the example.
	@if [ -f $(APP_HOME)/settings.toml ]; then :; \
	 elif [ -f settings.toml ]; then cp settings.toml $(APP_HOME)/settings.toml; \
	 else cp settings.example.toml $(APP_HOME)/settings.toml; fi
	@cp -f settings.example.toml $(APP_HOME)/
	@echo ">> Building native venv in $(APP_HOME)/.venv"
	python3 -m venv --system-site-packages $(APP_HOME)/.venv
	$(APP_HOME)/.venv/bin/pip install --upgrade pip "$(SETUPTOOLS_REQ)"
	cd $(APP_HOME) && .venv/bin/pip install -e . pywebview
	@$(APP_HOME)/.venv/bin/python -c "import gi; gi.require_version('WebKit2','4.0'); from gi.repository import WebKit2; print('WebKitGTK OK')" \
		|| (echo 'ERROR: system WebKitGTK missing — run the apt install in the header'; exit 1)
	@echo ">> Writing launcher -> $(APPLICATIONS_DIR)/conductor.desktop"
	@mkdir -p $(APPLICATIONS_DIR)
	@sed -e 's|@PYTHON@|$(APP_HOME)/.venv/bin/python|g' \
	     -e 's|@APPDIR@|$(APP_HOME)|g' \
	     packaging/conductor.desktop.in > $(APPLICATIONS_DIR)/conductor.desktop
	@update-desktop-database $(APPLICATIONS_DIR) 2>/dev/null || true
	@echo ""
	@echo "Installed. 'Conductor' is in your app menu (launches detached, no terminal)."
	@echo "Everything lives in $(APP_HOME) — this clone is now disposable."

uninstall-app:
	rm -rf $(APP_HOME)
	rm -f $(APPLICATIONS_DIR)/conductor.desktop
	@update-desktop-database $(APPLICATIONS_DIR) 2>/dev/null || true
	@echo "Removed $(APP_HOME) and the launcher."
