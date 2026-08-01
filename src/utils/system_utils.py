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
        "business": [
            (r'^.{10,500}$', "Business must be between 10 and 500 characters.")
        ],
        "target_audience": [
            (r'^.{10,500}$', "Target audience must be between 10 and 500 characters.")
        ],
        "objective": [
            (r'^.{10,500}$', "Objective must be between 10 and 500 characters.")
        ],
        "differential": [
            (r'^.{10,500}$', "Differential must be between 10 and 500 characters.")
        ],
        "personality": [
            (r'^.{10,500}$', "Personality must be between 10 and 500 characters.")
        ],
        "questions_personalized": [
            (r'^.{10,500}$', "Questions personalized must be between 10 and 500 characters.")
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