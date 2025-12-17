# fixes crash during 'import chromadb' - see: https://docs.trychroma.com/docs/overview/troubleshooting#sqlite
import sys
__import__("pysqlite3")
sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")

import os
os.environ["AZURE_OPENAI_API_KEY"] = "sk-xxxx"
os.environ["AZURE_OPENAI_SPEECH_ENDPOINT"] = "http://localhost:8000"