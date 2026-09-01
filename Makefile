PYTHON ?= python3
PREFIX ?= /opt/toolsapi-worker
SERVICE_NAME ?= toolsapi-worker
VENV ?= .venv
VENV_PYTHON := $(VENV)/bin/python
UNAME_S := $(shell uname -s)
UNAME_M := $(shell uname -m)

ifeq ($(UNAME_S),Darwin)
ifeq ($(UNAME_M),arm64)
LOCAL_WHISPER_EXTRA ?= whisper-mlx
else
LOCAL_WHISPER_EXTRA ?= whisper
endif
else
LOCAL_WHISPER_EXTRA ?= whisper
endif

.PHONY: help install install-system run status test lint check package smoke-install uninstall

help:
	@printf '%s\n' \
		'make install         Install into an isolated project virtual environment' \
		'make install-system  Install as an Ubuntu systemd or macOS launchd service' \
		'make run             Run the locally installed worker' \
		'make status          Show local worker status' \
		'make test            Run unit tests' \
		'make lint            Compile/import sanity checks' \
		'make check           Run lint and tests' \
		'make package         Build wheel/source distribution' \
		'make smoke-install   Test isolated package installation' \
		'make uninstall       Remove the platform service installation'

install:
	$(PYTHON) -m venv "$(VENV)"
	"$(VENV_PYTHON)" -m pip install --upgrade pip setuptools wheel
	"$(VENV_PYTHON)" -m pip install ".[${LOCAL_WHISPER_EXTRA}]"
	@printf '%s\n' "Installed toolsapi-worker in $(VENV)."
	@printf '%s\n' "Run with: make run"
	@if [ "$(UNAME_S)" = "Darwin" ] && [ "$(UNAME_M)" = "arm64" ] && ! command -v ffmpeg >/dev/null 2>&1; then \
		printf '%s\n' 'Whisper on macOS also requires ffmpeg: brew install ffmpeg'; \
	fi

install-system:
	@if [ "$(UNAME_S)" = "Darwin" ]; then \
		bash ./scripts/install-macos.sh; \
	else \
		sudo ./scripts/install.sh; \
	fi

run:
	@"$(VENV)/bin/toolsapi-worker" run

status:
	@"$(VENV)/bin/toolsapi-worker" status

test:
	$(PYTHON) -m unittest discover -s tests -v

lint:
	$(PYTHON) -m compileall -q src tests
	$(PYTHON) -m toolsapi_worker.cli --version

check: lint test

package:
	$(PYTHON) -m pip install --upgrade build
	$(PYTHON) -m build

smoke-install:
	./scripts/smoke-install.sh

uninstall:
	@if [ "$(UNAME_S)" = "Darwin" ]; then \
		bash ./scripts/uninstall-macos.sh; \
	else \
		sudo ./scripts/uninstall.sh; \
	fi
