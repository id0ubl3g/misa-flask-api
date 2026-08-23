from email_validator import validate_email, EmailNotValidError

from pathlib import Path
import json
import sys
import os
import re

def parse_ai_json(text: str) -> dict:
    text = text.replace('```json', '')
    text = text.replace('```', '')
    text = text.strip()

    return json.loads(text)

def is_valid_email(email: str) -> bool:
    try:
        validate_email(email)
        return True
    
    except EmailNotValidError:
        return False

def validate_user_data(data: dict) -> str | None:
    validators = {
        "name_project": [
            (r'^[A-Za-z0-9À-ÿ ]{3,100}$',
            "Project name must be between 3 and 100 characters and contain only letters and numbers.")
        ],
        "name_client": [
            (r'^[A-Za-z0-9À-ÿ ]{2,100}$',
            "Client name must be between 2 and 100 characters and contain only letters and numbers.")
        ],
        "business": [
            (r'^[A-Za-z0-9À-ÿ ]{10,500}$',
            "Business must be between 10 and 500 characters and contain only letters and numbers.")
        ],
        "target_audience": [
            (r'^[A-Za-z0-9À-ÿ ]{10,500}$',
            "Target audience must be between 10 and 500 characters and contain only letters and numbers.")
        ],
        "objective": [
            (r'^[A-Za-z0-9À-ÿ ]{10,500}$',
            "Objective must be between 10 and 500 characters and contain only letters and numbers.")
        ],
        "differential": [
            (r'^[A-Za-z0-9À-ÿ ]{10,500}$',
            "Differential must be between 10 and 500 characters and contain only letters and numbers.")
        ],
        "personality": [
            (r'^[A-Za-z0-9À-ÿ ]{10,500}$',
            "Personality must be between 10 and 500 characters and contain only letters and numbers.")
        ],
        "questions_personalized": [
            (r'^[A-Za-z0-9À-ÿ ]{10,500}$',
            "Questions personalized must be between 10 and 500 characters and contain only letters and numbers.")
        ],
        "token": [
            (r'^[a-f0-9]{12}$', "Token must be a valid 12-character hexadecimal string.")
        ],
        "success_url": [
            (r'^https://', "Success URL must start with https://"),
            (r'^.{1,2083}$', "Success URL must be between 1 and 2083 characters long"),
            (r'^https://([\w\-]+\.)+[\w\-]+(/[\w\-./?%&=]*)?$', "Success URL format is invalid")
        ],
        "failure_url": [
            (r'^https://', "Failure URL must start with https://"),
            (r'^.{1,2083}$', "Failure URL must be between 1 and 2083 characters long"),
            (r'^https://([\w\-]+\.)+[\w\-]+(/[\w\-./?%&=]*)?$', "Failure URL format is invalid")
        ],
        "pending_url": [
            (r'^https://', "Pending URL must start with https://"),
            (r'^.{1,2083}$', "Pending URL must be between 1 and 2083 characters long"),
            (r'^https://([\w\-]+\.)+[\w\-]+(/[\w\-./?%&=]*)?$', "Pending URL format is invalid")
        ]
    }

    for field, rules in validators.items():
        value = data.get(field)

        if value is None:
            continue

        value = str(value).strip()

        if value == "":
            continue

        for pattern, error_msg in rules:
            if not re.match(pattern, value):
                return error_msg

    return None

def create_google_credentials() -> str:
    try:
        credentials = {
            "type": os.environ["GOOGLE_TYPE"],
            "project_id": os.environ["GOOGLE_PROJECT_ID"],
            "private_key_id": os.environ["GOOGLE_PRIVATE_KEY_ID"],
            "private_key": os.environ["GOOGLE_PRIVATE_KEY"].replace("\\n", "\n"),
            "client_email": os.environ["GOOGLE_CLIENT_EMAIL"],
            "client_id": os.environ["GOOGLE_CLIENT_ID"],
            "auth_uri": os.environ["GOOGLE_AUTH_URI"],
            "token_uri": os.environ["GOOGLE_TOKEN_URI"],
            "auth_provider_x509_cert_url": os.environ["GOOGLE_AUTH_PROVIDER_X509_CERT_URL"],
            "client_x509_cert_url": os.environ["GOOGLE_CLIENT_X509_CERT_URL"],
            "universe_domain": os.environ["GOOGLE_UNIVERSE_DOMAIN"],
        }

    except Exception:
        print('Error occurred while creating Google credentials')
        sys.exit(1)


    path = Path("config/misa-flask-api-501622-91fd8aef25fd.json")

    with path.open("w") as file:
        json.dump(credentials, file, indent=2)

    return path