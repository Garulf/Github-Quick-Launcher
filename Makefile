VENV = venv
PYTHON = $(VENV)/bin/python3
PIP = $(VENV)/bin/pip
PLUGIN_NAME = $(shell jq -r '.Name' ./src/plugin.json | tr " " "-")
PLUGIN_VERSION = $(shell jq -r '.Version' ./src/plugin.json)
PLUGIN_DIR = $(PLUGIN_NAME)-$(PLUGIN_VERSION)
ZIP_FILE = $(PLUGIN_DIR).zip


venv:
	python3 -m venv $(VENV)
	$(PIP) install -r requirements.txt
	$(PIP) install -r requirements-dev.txt

init: venv

test: venv
	$(PYTHON) -m pytest

tox: venv
	$(PYTHON) -m tox

cleanvenv:
	rm -rf __pycache__
	rm -rf $(VENV)

cleantox:
	rm -rf .tox

cleanall: cleanvenv cleantox cleanbuild cleandist

cleanbuild:
	rm -rf build

cleandist:
	rm -rf dist

lib:
	mkdir -p lib
	python3 -m pip install -r requirements.txt -t ./lib

build: lib
	mkdir -p build
	find ./src -name '*.py' -exec cp {} ./build \;
	cp -R ./lib/. ./build

./dist/*.pyz: build dist
	python3 -m zipapp --output="./dist/$(PLUGIN_NAME).pyz" ./build

zipapp: ./dist/*.pyz

dist: build
	mkdir -p dist
	find ./src -not -name '*.py*' -not -name 'src' -not -name '__pycache__' -exec cp -r {} ./dist \;

package: ./dist/*.pyz
	cd ./dist && zip -r ../$(ZIP_FILE) *

installplugin: dist
	mkdir -p $(INSTALL_DIR)/$(PLUGIN_DIR)
	cp -R ./dist/. $(INSTALL_DIR)/$(PLUGIN_DIR)/

zipname:
	@echo $(PLUGIN_DIR).zip
	