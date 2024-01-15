VENV = venv
PYTHON = $(VENV)/bin/python3
PIP = $(VENV)/bin/pip
PLUGIN_NAME = $(shell jq -r '.Name' ./src/plugin.json | tr " " "-")
PLUGIN_VERSION = $(shell jq -r '.Version' ./src/plugin.json)
PLUGIN_DIR = $(PLUGIN_NAME)-$(PLUGIN_VERSION)
ZIP_FILE = $(PLUGIN_DIR).zip

$(VENV)/bin/activate:
	python3 -m venv $(VENV)

venv: $(VENV)/bin/activate

install: $(VENV)/bin/activate requirements.txt
	$(PIP) install -r requirements.txt

installdev: $(VENV)/bin/activate requirements-dev.txt
	$(PIP) install -r requirements-dev.txt

test: install installdev
	$(PYTHON) -m pytest

tox:
	$(PYTHON) -m tox

cleanvenv:
	rm -rf __pycache__
	rm -rf $(VENV)

cleantox:
	rm -rf .tox

clean: cleanvenv cleantox cleanbuild cleandist

cleanbuild:
	rm -rf build

cleandist:
	rm -rf dist

build:
	mkdir -p build
	find ./src -name '*.py' -exec cp {} ./build \;
	python3 -m pip install -r requirements.txt -t ./build

./dist/*.pyz: build dist
	python3 -m zipapp --output="./dist/$(PLUGIN_NAME)" ./build

zipapp: ./dist/*.pyz

dist: build
	mkdir -p dist
	find ./src -not -name '*.py*' -not -name 'src' -not -name '__pycache__' -exec cp -r {} ./dist \;

package: ./dist/*.pyz
	cd ./dist && zip -r ../$(ZIP_FILE) *

installplugin: dist
	mkdir -p $(INSTALL_DIR)/$(PLUGIN_DIR)
	cp -R ./dist/. $(INSTALL_DIR)/$(PLUGIN_DIR)/


	