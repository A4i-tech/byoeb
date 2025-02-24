#!/bin/bash

# # Debug: Print the current environment
# echo "Current virtual environment: $VIRTUAL_ENV"

# # Properly deactivate the existing virtual environment if active
# if [ -n "$VIRTUAL_ENV" ]; then
#     deactivate
#     unset VIRTUAL_ENV
# fi

# # Debug: Check if environment is unset
# echo "After deactivating: $VIRTUAL_ENV"

# # Remove existing Poetry
# curl -sSL https://install.python-poetry.org | python3 - --uninstall
# curl -sSL https://install.python-poetry.org | python3 - --version 2.1.1

# # Set up Poetry correctly
# echo 'export PATH="/root/.local/bin:$PATH"' >> ~/.bashrc
# source ~/.bashrc
# poetry config virtualenvs.in-project true

# # Ensure a clean Python environment
# export PIP_NO_BINARY=:all:
# export PIP_NO_CACHE_DIR=off

# # Navigate to project directories and install dependencies
# cd byoeb-v1/byoeb-core
# poetry install --no-interaction
# poetry build

# cd ../byoeb-integrations
# poetry install --no-interaction
# poetry build

# cd ../byoeb
# poetry install --no-interaction

# # Explicitly activate the new Poetry environment
# eval "$(poetry env info --path)/bin/activate"
python byoeb-v1/byoeb/byoeb/chat_app/run.py
