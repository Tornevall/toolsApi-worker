PYTHON ?= python3
PREFIX ?= /opt/toolsapi-worker
CONFIG_DIR ?= /etc/toolsapi-worker
SERVICE_NAME ?= toolsapi-worker

.PHONY: help install install-system test lint check package smoke-install uninstall

help:
	@printf '%s\n' \
		'make install         Install into the current user environment' \
		'make install-system  Install as an Ubuntu systemd service (sudo required)' \
		'make test            Run unit tests' \
		'make lint            Compile/import sanity checks' \
		'make check           Run lint and tests' \
		'make package         Build wheel/source distribution' \
		'make smoke-install   Test isolated package installation' \
		'make uninstall       Remove system installation (sudo required)'

install:
	$(PYTHON) -m pip install .

install-system:
	sudo ./scripts/install.sh

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
	sudo ./scripts/uninstall.sh
