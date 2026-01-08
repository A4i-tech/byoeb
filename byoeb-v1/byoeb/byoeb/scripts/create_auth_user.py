import argparse
import getpass
import uuid

from pymongo import MongoClient

from byoeb.chat_app.configuration.config import app_config
from byoeb.services.auth.security import hash_password


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an admin user in the auth collection.")
    parser.add_argument("--mongo-uri", required=True, help="MongoDB connection string.")
    parser.add_argument("--username", required=True, help="Auth username.")
    parser.add_argument("--password", help="Auth password (prompted if omitted).")
    parser.add_argument("--tenant-id", required=True, help="Tenant ID for the auth user.")
    parser.add_argument("--roles", required=True, help="Comma-separated roles.")
    args = parser.parse_args()
    password = args.password or getpass.getpass("Password: ")
    if not password:
        raise SystemExit("Password is required.")
    try:
        tenant_id = uuid.UUID(args.tenant_id)
    except ValueError as exc:
        raise SystemExit(f"Invalid tenant-id (not a UUID): {args.tenant_id}") from exc

    database_name = app_config["databases"]["mongo_db"]["database_name"]
    collection_name = app_config["databases"]["mongo_db"]["auth_user_collection"]
    role_collection_name = app_config["databases"]["mongo_db"]["auth_tenant_roles_collection"]
    roles = [role.strip() for role in args.roles.split(",") if role.strip()]

    password_salt, password_hash = hash_password(password)

    client = MongoClient(args.mongo_uri, uuidRepresentation="standard")
    collection = client[database_name][collection_name]

    existing = collection.find_one({"username": args.username})
    if existing:
        print("User already exists. No changes made.")
        return 1

    tenant_collection = client[database_name][app_config["databases"]["mongo_db"]["auth_tenant_collection"]]
    tenant_doc = tenant_collection.find_one({"_id": tenant_id})
    if not tenant_doc:
        print("Tenant not found. No changes made.")
        return 1
    role_collection = client[database_name][role_collection_name]
    roles_doc = role_collection.find_one({"_id": tenant_id}) or {}
    tenant_roles = set((roles_doc.get("roles") or {}).keys())
    if not set(roles).issubset(tenant_roles):
        print("One or more roles are not defined for this tenant. No changes made.")
        return 1

    collection.insert_one({
        "_id": uuid.uuid4(),
        "username": args.username,
        "tenants": [{"tenant_id": tenant_id, "roles": roles}],
        "password_salt": password_salt,
        "password_hash": password_hash,
    })
    print("Auth user created.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
