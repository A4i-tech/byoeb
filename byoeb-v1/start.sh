#!/bin/bash

unset VIRTUAL_ENV
curl -sSL https://install.python-poetry.org | python3 - --uninstall
curl -sSL https://install.python-poetry.org | python3 - --version 2.1.1
echo 'export PATH="/root/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
poetry config virtualenvs.in-project true

cd byoeb-v1/byoeb-core
poetry install --no-interaction
poetry build

cd ../byoeb-integrations
poetry install --no-interaction
poetry build

cd ../byoeb
poetry install --no-interaction
source "$(poetry env info --path)/bin/activate"
python byoeb/chat_app/run.py