from pymongo.errors import OperationFailure
from pymongo import MongoClient
from dotenv import load_dotenv
import sys
import os

load_dotenv()

def initialize_mongodb():
    mongo_uri = os.getenv('MONGO_URI')
    client = MongoClient(mongo_uri, tz_aware=True)
    db = client['misa-flask-api']

    clients_collection = db["clients_collection"]
    clients_collection.create_index("designer_uid")
    clients_collection.create_index("token", unique=True)

    try:
        clients_collection.create_index(
            [("designer_uid", 1), ("email_client", 1)],
            unique=True,
            name="designer_uid_1_email_client_1"
        )
    except OperationFailure as error:
        print(
            "WARNING: could not create the unique index on (designer_uid, email_client). "
            "Deduplicate the existing clients and restart to enforce it. "
            f"Reason: {error}",
            file=sys.stderr
        )

    users_collection = db["users_collection"]
    users_collection.create_index("email", unique=True)
    users_collection.create_index("uid", unique=True)

    transactions_collection = db["transactions_collection"]
    transactions_collection.create_index("transaction_id",unique=True)
    transactions_collection.create_index("expires_at", expireAfterSeconds=0)

    return {
        "client": client,
        "db": db,
        "clients_collection": clients_collection,
        "users_collection": users_collection,
        "transactions_collection": transactions_collection
    }