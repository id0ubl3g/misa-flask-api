from dotenv import load_dotenv
from firebase_admin import credentials
import firebase_admin
import os

load_dotenv()

def initialize_firebase() -> None:
    if firebase_admin._apps:
        return

    firebase_credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    cred = credentials.Certificate(firebase_credentials_path)

    firebase_admin.initialize_app(cred)