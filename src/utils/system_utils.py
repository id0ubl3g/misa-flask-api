from email_validator import validate_email, EmailNotValidError

import json
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
            (r'^.{3,100}$', "Project name must be between 3 and 100 characters.")
        ],
        "name_client": [
            (r'^.{2,100}$', "Client name must be between 2 and 100 characters.")
        ],
        "problem": [
            (r'^.{10,500}$', "Problem must be between 10 and 500 characters.")
        ],
        "target_audience": [
            (r'^.{5,300}$', "Target audience must be between 5 and 300 characters.")
        ],
        "goal": [
            (r'^.{10,300}$', "Goal must be between 10 and 300 characters.")
        ],
        "requirements": [
            (r'^.{10,500}$', "Requirements must be between 10 and 500 characters.")
        ],

        "constraints": [
            (r'^.{5,300}$', "Constraints must be between 5 and 300 characters.")
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