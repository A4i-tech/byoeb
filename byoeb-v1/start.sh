pip install poetry
poetry config virtualenvs.in-project true

cd byoeb-v1/byoeb-core
poetry install --no-interaction
poetry build

cd ..
cd byoeb-integrations
poetry install --no-interaction
poetry add ../byoeb-core/dist/byoeb_core-0.1.0-py3-none-any.whl 

cd ..
cd byoeb
poetry install --no-interaction
poetry add ../byoeb-integrations/dist/byoeb_integrations-0.1.0-py3-none-any.whl
poetry shell
python byoeb/chat_app/run.py

