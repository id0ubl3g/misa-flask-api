from src.modules.generative_ai import GenerativeAI

from config.initial_questions import initial_questions
from config.prompt_config import prompt_refine_questions

from config.providers.initialize_mongodb import initialize_mongodb

from src.utils.system_utils import parse_ai_json, validate_user_data, is_valid_email

from flask import Flask, request, jsonify, Response
from datetime import datetime, timezone
from dotenv import load_dotenv
from flask_cors import CORS
import secrets

load_dotenv()

class Server:
    def __init__(self) -> None:
        self.app: Flask = Flask(__name__)

        mongo = initialize_mongodb()

        self.clients_collection: Collection = mongo["clients_collection"]

        CORS(
            self.app,
            origins="*",
            allow_headers=["Content-Type", "Authorization"],
            methods=["GET", "POST", "PUT", "PATCH", "DELETE"]
        )

        self._register_routes()

    def create_error_response(self, message: str, code: int) -> Response:
        return jsonify({'error': message}), code

    def _register_routes(self) -> None:
        @self.app.route('/misa/briefing/ping', methods=['POST'])
        def misa_briefing_ping() -> Response:
                try:
                    data = request.get_json()

                    initial_questions = data.get('initial_questions')
                    
                    if initial_questions == 'True':
                        return jsonify(initial_questions), 200

                    name_project = data.get('name_project')
                    name_client = data.get('name_client')
                    email_client = data.get('email_client')

                    problem = data.get('problem')
                    target_audience = data.get('target_audience')
                    goal = data.get('goal')
                    requirements = data.get('requirements')
                    constraints = data.get('constraints')

                    if not name_project or not name_client or not email_client or not problem or not target_audience or not goal or not requirements or not constraints:
                        return self.create_error_response(f'Missing required fields: {", ".join(["name_project", "name_client", "email_client", "problem", "target_audience", "goal", "requirements", "constraints"])}', 400)

                    if not is_valid_email(email_client):
                        return self.create_error_response('Invalid email format', 400)

                    client_exists = self.clients_collection.find_one({'emai_client': email_client})
                    if client_exists:
                        return self.create_error_response('A client with this email already exists.', 400)

                    if not problem or not target_audience or not goal or not requirements or not constraints:
                        return self.create_error_response(f'Missing required fields: {", ".join(["problem", "target_audience", "goal", "requirements", "constraints"])}', 400)

                    validation_error = validate_user_data({
                        "name_project": name_project,
                        "name_client": name_client,
                        "problem": problem,
                        "target_audience": target_audience,
                        "goal": goal,
                        "requirements": requirements,
                        "constraints": constraints
                    })

                    if validation_error:
                        return self.create_error_response(validation_error, 400)

                    questions = {
                        "initial_questions": {
                            initial_questions['initial_questions']['problem']: problem,
                            initial_questions['initial_questions']['target_audience']: target_audience,
                            initial_questions['initial_questions']['goal']: goal,
                            initial_questions['initial_questions']['requirements']: requirements,
                            initial_questions['initial_questions']['constraints']: constraints
                        }
                    }

                    merged_prompt = f"{prompt_refine_questions}{questions}"
                    response_generative_ai = GenerativeAI().start_chat(merged_prompt)
                    response_generative_ai_json = parse_ai_json(response_generative_ai['data'])

                    client_data = {
                        "designer": None,
                        "name_project": name_project,
                        "name_client": name_client,
                        "emai_client": email_client,
                        "token": secrets.token_hex(6),
                        "initial_questions": questions,
                        "questions_personalized": response_generative_ai_json,
                        "briefing": False,
                        "created_at": datetime.now(timezone.utc)
                    }

                    self.clients_collection.insert_one(client_data)

                    return jsonify({
                        "message": "Brand briefing received successfully. Personalized follow-up questions generated.",
                        "token": client_data["token"],
                        "questions": response_generative_ai_json
                    }), 201

                except Exception:
                    return self.create_error_response('An error occurred while processing the request', 500)


    def run_production(self, host: str = '0.0.0.0', port: int = 5000) -> None:
        self.app.run(debug=False, host=host, port=port, use_reloader=False)

    
