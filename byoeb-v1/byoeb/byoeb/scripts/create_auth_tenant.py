import argparse
import uuid

from pymongo import MongoClient

from byoeb.chat_app.configuration.config import app_config


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an auth tenant in the auth collection.")
    parser.add_argument("--mongo-uri", required=True, help="MongoDB connection string.")
    parser.add_argument("--name", required=True, help="Tenant display name.")
    args = parser.parse_args()

    database_name = app_config["databases"]["mongo_db"]["database_name"]
    collection_name = app_config["databases"]["mongo_db"]["auth_tenant_collection"]
    role_collection_name = app_config["databases"]["mongo_db"]["auth_tenant_roles_collection"]

    client = MongoClient(args.mongo_uri, uuidRepresentation="standard")
    collection = client[database_name][collection_name]
    role_collection = client[database_name][role_collection_name]

    tenant_id = uuid.uuid4()
    existing = collection.find_one({"_id": tenant_id})
    if existing:
        print("Tenant already exists. No changes made.")
        return 1

    roles = app_config.get("default_tenant_roles", {})
    collection.insert_one({"_id": tenant_id, "name": args.name})
    role_collection.insert_one({"_id": tenant_id, "roles": roles})
    print(f"Tenant created: {tenant_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
