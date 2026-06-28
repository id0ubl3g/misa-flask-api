from pymongo import MongoClient
from dotenv import load_dotenv
import os

load_dotenv()

def initialize_mongodb():
    mongo_uri = os.getenv('MONGO_URI')
    client = MongoClient(mongo_uri, tz_aware=True)
    db = client['misa-flask-api']

    clients_collection = db["clients_collection"]
    clients_collection.create_index("email_client", unique=True)

    users_collection = db["users_collection"]
    users_collection.create_index("email", unique=True)
    users_collection.create_index("uid", unique=True)

    return {
        "client": client,
        "db": db,
        "clients_collection": clients_collection,
        "users_collection": users_collection
    }