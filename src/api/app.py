from src.modules.generative_ai import GenerativeAI

from config.model_questions_personalized import model_questions_personalized
from config.model_initial_questions import model_initial_questions
from config.prompt_config import prompt_questions_personalized, prompt_generate_briefing

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
        @self.app.route('/misa/briefing/start', methods=['POST'])
        def misa_briefing_start() -> Response:
            try:
                data = request.get_json()

                name_project = data.get('name_project')
                name_client = data.get('name_client')
                email_client = data.get('email_client')

                if not name_project or not name_client or not email_client:
                    return self.create_error_response(f'Missing required fields: {", ".join(["name_project", "name_client", "email_client"])}', 400)

                if not is_valid_email(email_client):
                    return self.create_error_response('Invalid email format', 400)

                client_exists = self.clients_collection.find_one({'email_client': email_client})
                if client_exists:
                    if client_exists.get('briefing'):
                        return self.create_error_response('A brand briefing already exists for this client.', 409)

                    return self.create_error_response('A client with this email already exists.', 400)

                validation_error = validate_user_data({
                        "name_project": name_project,
                        "name_client": name_client,
                    })

                if validation_error:
                    return self.create_error_response(validation_error, 400)

                client_data = {
                    "designer": None,
                    "name_project": name_project,
                    "name_client": name_client,
                    "email_client": email_client,
                    "token": secrets.token_hex(6),
                    "initial_questions_completed": False,
                    "questions_personalized_completed": False,
                    "briefing": False,
                    "created_at": datetime.now(timezone.utc)
                }

                self.clients_collection.insert_one(client_data)

                return jsonify({
                    "message": "Client created successfully. Ready to start the brand briefing.",
                    "token": client_data["token"],
                }), 201
                
            except Exception:
                return self.create_error_response('An error occurred while processing the request', 500)
                
        @self.app.route('/misa/briefing/ping/<string:token>', methods=['POST'])
        def misa_briefing_ping(token: str) -> Response:
            try:
                data = request.get_json()

                initial_questions = data.get('model_initial_questions')
                
                if initial_questions == 'True':
                    return jsonify(model_initial_questions), 200

                business = data.get('business')
                target_audience = data.get('target_audience')
                objective = data.get('objective')
                differential = data.get('differential')
                personality = data.get('personality')

                if not business or not target_audience or not objective or not differential or not personality:
                    return self.create_error_response(f'Missing required fields: {", ".join(["business", "target_audience", "objective", "differential", "personality"])}', 400)

                validation_error = validate_user_data({
                    "token": token,
                    "business": business,
                    "target_audience": target_audience,
                    "objective": objective,
                    "differential": differential,
                    "personality": personality
                })

                if validation_error:
                    return self.create_error_response(validation_error, 400)

                client_exists = self.clients_collection.find_one({'token': token})
                if not client_exists:
                    return self.create_error_response('No client found with the provided token.', 400)

                if client_exists.get('initial_questions_completed'):
                    return self.create_error_response('Initial questions have already been completed.', 400)

                questions = {
                    "question 1": {
                        "question": model_initial_questions['model_initial_questions']['business'],
                        "answer": business
                    },
                    "question 2": {
                        "question": model_initial_questions['model_initial_questions']['target_audience'],
                        "answer": target_audience
                    },
                    "question 3": {
                        "question": model_initial_questions['model_initial_questions']['objective'],
                        "answer": objective
                    },
                    "question 4": {
                        "question": model_initial_questions['model_initial_questions']['differential'],
                        "answer": differential
                    },
                    "question 5": {
                        "question": model_initial_questions['model_initial_questions']['personality'],
                        "answer": personality
                    }
                }

                merged_prompt = f"{prompt_questions_personalized}{questions}"
                response_generative_ai = GenerativeAI().start_chat(merged_prompt)
                response_generative_ai_json = parse_ai_json(response_generative_ai['data'])

                self.clients_collection.update_one(
                    {"token": token},
                    {
                        "$set": {
                            "questions": {
                                "initial_questions": questions,
                                "questions_personalized": response_generative_ai_json
                            },
                            "initial_questions_completed": True
                        }
                    }
                )

                return jsonify({
                    "message": "Brand briefing received successfully. Personalized follow-up questions generated.",
                    "questions": response_generative_ai_json,
                    "token": token

                }), 201

            except Exception:
                return self.create_error_response('An error occurred while processing the request', 500)

        @self.app.route('/misa/briefing/pong/<string:token>', methods=['POST'])
        def misa_briefing_pong(token: str) -> Response:
            try:
                data = request.get_json()

                model_questions_personalized = data.get('model_questions_personalized')

                if model_questions_personalized == 'True':
                    return jsonify(model_questions_personalized), 200

                current_info_client = self.clients_collection.find_one({'token': token})
                if not current_info_client:
                    return self.create_error_response('Client not found.', 404)

                client_exists = self.clients_collection.find_one({'token': token})
                if not client_exists.get('initial_questions_completed'):
                    return self.create_error_response('Initial questions have not been completed yet.', 400)
                
                if client_exists.get('questions_personalized_completed'):
                    return self.create_error_response('Questions personalized have already been completed.', 400)

                context_questions = data.get('context_questions', {})
                refinement_questions = data.get('refinement_questions', {})

                if not context_questions or not refinement_questions:
                    return self.create_error_response(f'Missing required fields: {", ".join(["context_questions", "refinement_questions"])}', 400)

                if len(context_questions) != 5:
                    return self.create_error_response('Context questions must contain exactly 5 answers.', 400)

                if len(refinement_questions) != 5:
                    return self.create_error_response('Refinement questions must contain exactly 5 answers.', 400)

                initial_questions = current_info_client['questions']['initial_questions']
                _context_questions = current_info_client['questions']['questions_personalized']['context_questions']
                _refinement_questions = current_info_client['questions']['questions_personalized']['refinement_questions']
                
                data_context_questions = {}
                data_refinement_questions = {}

                for i in range(1, 6):
                    question = _context_questions.get(f'question {i}')
                    answer = context_questions.get(f'question {i}')

                    validation_error = validate_user_data({
                        "questions_personalized": answer
                    })

                    if validation_error:
                        return self.create_error_response(validation_error, 400)

                    data_context_questions[f'question {i}'] = {
                        "question": question,
                        "answer": answer
                    }

                for i in range(1, 6):
                    question = _refinement_questions.get(f'question {i}')
                    answer = refinement_questions.get(f'question {i}')

                    validation_error = validate_user_data({
                        "questions_personalized": answer,
                    })

                    if validation_error:
                        return self.create_error_response(validation_error, 400)

                    data_refinement_questions[f'question {i}'] = {
                        "question": question,
                        "answer": answer
                    }

                merged_prompt = f"{prompt_generate_briefing}{initial_questions}{data_context_questions}{data_refinement_questions}"
                response_generative_ai = GenerativeAI().start_chat(merged_prompt)
                response_generative_ai_json = parse_ai_json(response_generative_ai['data'])

                self.clients_collection.update_one(
                    {"token": token},
                    {
                        "$set": {
                            "questions.questions_personalized.context_questions": data_context_questions,
                            "questions.questions_personalized.refinement_questions": data_refinement_questions,
                            "questions_personalized_completed": True,
                            "briefing": True
                        }
                    }
                )
                                
                return jsonify(response_generative_ai_json)

            except Exception:
                return self.create_error_response('An error occurred while processing the request', 500)

    def run_production(self, host: str = '0.0.0.0', port: int = 5000) -> None:
        self.app.run(debug=False, host=host, port=port, use_reloader=False)

    
