from src.modules.generative_ai import GenerativeAI

from config.model_questions_personalized import model_questions_personalized
from config.model_initial_questions import model_initial_questions
from config.prompt_config import prompt_questions_personalized, prompt_generate_briefing

from config.providers.initialize_mongodb import initialize_mongodb
from config.providers.initialize_firebase import initialize_firebase

from src.utils.system_utils import parse_ai_json, validate_user_data, is_valid_email

from flask_jwt_extended import JWTManager, create_access_token, create_refresh_token, jwt_required, get_jwt_identity, verify_jwt_in_request
from flask import Flask, request, jsonify, Response
from datetime import datetime, timezone, timedelta
from firebase_admin import auth
from dotenv import load_dotenv
from flask_cors import CORS
import secrets
import os

load_dotenv()

class Server:
    def __init__(self) -> None:
        self.app: Flask = Flask(__name__)

        self.app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY')
        self.app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=1)
        self.app.config['JWT_REFRESH_TOKEN_EXPIRES'] = timedelta(days=30)

        self.jwt: JWTManager = JWTManager(self.app)

        mongo = initialize_mongodb()
        initialize_firebase()

        self.clients_collection: Collection = mongo["clients_collection"]
        self.users_collection: Collection = mongo["users_collection"]

        CORS(
            self.app,
            origins="*",
            allow_headers=["Content-Type", "Authorization"],
            methods=["GET", "POST", "PUT", "PATCH", "DELETE"]
        )

        self._register_routes()

    def create_error_response(self, message: str, code: int) -> Response:
        return jsonify({'error': message}), code

    def get_user(self, uid) -> dict | None:
        return self.users_collection.find_one({"uid": uid})

    def user_or_ip(self) -> str | None:
            try:
                verify_jwt_in_request()
                identity = get_jwt_identity()
                if identity:
                    return identity
                
            except Exception:
                endpoint = request.endpoint
                endpoints_require = ['misa_briefing_create_client', 'misa_getall_client_responses', 
                                    'misa_get_client_response_by_token', 'misa_refresh_token']

                if endpoint not in (endpoints_require):
                    return get_remote_address()
                
                return False
                
    def _register_routes(self) -> None:
        @self.app.route('/misa/briefing/create_client', methods=['POST'])
        @jwt_required()
        def misa_briefing_create_client() -> Response:
            try:
                current_user = self.user_or_ip()

                if not current_user:
                    return self.create_error_response("You are not authorized to access this resource", 401)

                current_info_user = self.get_user(current_user)

                if not current_info_user:
                    return self.create_error_response("User not found", 404)

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
                    "designer": current_info_user['name'],
                    "designer_uid": current_info_user['uid'],
                    "name_project": name_project,
                    "name_client": name_client,
                    "email_client": email_client,
                    "token": secrets.token_hex(6),
                    "initial_questions_completed": False,
                    "questions_personalized_completed": False,
                    "briefing": False,
                    "briefing_data": None,
                    "created_at": datetime.now(timezone.utc)
                }

                self.clients_collection.insert_one(client_data)

                return jsonify({
                    "message": "Client created successfully. Ready to start the brand briefing.",
                    "token": client_data["token"],
                }), 201
                
            except Exception:
                return self.create_error_response('An error occurred while processing the request', 500)
                
        @self.app.route('/misa/briefing/ping_client_response/<string:token>', methods=['POST'])
        def misa_briefing_ping_client_response(token: str) -> Response:
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

        @self.app.route('/misa/briefing/pong_client_response/<string:token>', methods=['POST'])
        def misa_briefing_pong_client_response(token: str) -> Response:
            try:
                data = request.get_json()

                questions_personalized = data.get('model_questions_personalized')

                if questions_personalized == 'True':
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
                            "briefing": True,
                            "briefing_data": response_generative_ai_json
                        }
                    }
                )
                                
                return jsonify(response_generative_ai_json)

            except Exception:
                return self.create_error_response('An error occurred while processing the request', 500)

        @self.app.route('/misa/getall_client_responses', methods=['GET'])
        @jwt_required()
        def misa_getall_client_responses() -> Response:
            try:
                current_user = self.user_or_ip()

                if not current_user:
                    return self.create_error_response("You are not authorized to access this resource", 401)

                current_info_user = self.get_user(current_user)

                if not current_info_user:
                    return self.create_error_response("User not found", 404)

                client_responses = self.clients_collection.find({
                    "designer_uid": current_info_user['uid']
                })

                responses = []

                for response in client_responses:
                    responses.append({
                        "designer": response['designer'],
                        "designer_uid": response['designer_uid'],
                        "name_project": response['name_project'],
                        "name_client": response['name_client'],
                        "email_client": response['email_client'],
                        "token": response['token'],
                        "initial_questions_completed": response['initial_questions_completed'],
                        "questions_personalized_completed": response['questions_personalized_completed'],
                        "briefing": response['briefing'],
                        "created_at": response['created_at']
                    })  

                return jsonify({
                    "message": "Client responses retrieved successfully.",
                    "responses": responses
                }), 200

            except Exception:
                return self.create_error_response('An error occurred while processing the request', 500)

        @self.app.route('/misa/get_client_response/<string:token>', methods=['GET'])
        @jwt_required()
        def misa_get_client_response_by_token(token: str) -> Response:
            try:
                current_user = self.user_or_ip()

                if not current_user:
                    return self.create_error_response("You are not authorized to access this resource", 401)

                current_info_user = self.get_user(current_user)

                if not current_info_user:
                    return self.create_error_response("User not found", 404)

                client_response = self.clients_collection.find_one({
                    "designer_uid": current_info_user['uid'],
                    "token": token 
                })

                client_response["_id"] = str(client_response["_id"])

                return jsonify({
                    "message": "Client response retrieved successfully.",
                    "response": client_response
                }), 200

            except Exception:
                return self.create_error_response('An error occurred while processing the request', 500)

        @self.app.route("/misa/auth/google", methods=["POST"])
        def misa_auth_google():
            try:
                token = request.json.get("token")
                decoded_token = auth.verify_id_token(token)

                uid = decoded_token["uid"]
                email = decoded_token["email"]
                name = decoded_token.get("name")

                user = self.users_collection.find_one({"uid": uid})

                access_token = create_access_token(identity=uid)
                refresh_token = create_refresh_token(identity=uid)
                
                if not user:
                    self.users_collection.insert_one({
                        "uid": uid,
                        "email": email,
                        "name": name,
                        "is_free": True,
                        "created_at": datetime.now(timezone.utc)
                    })

                    return jsonify({
                        "message": "Account created successfully.",
                        "new_user": True,
                        "access_token": access_token,
                        "refresh_token": refresh_token,
                        "user": {
                            "email": email,
                            "name": name
                        }
                    }), 201

                return jsonify({
                    "message": "Authentication completed successfully.", 
                    "new_user": False,
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "user": {
                        "email": email,
                        "name": name
                    }
                }), 200

            except Exception:
                return self.create_error_response('An error occurred while processing the request', 500)

        @self.app.route('/misa/refresh_token', methods=['POST'])
        @jwt_required(refresh=True)
        def misa_refresh_token() -> Response:
            try:                
                current_user = get_jwt_identity()

                if not current_user:
                    return self.create_error_response("You are not authorized to access this resource", 401)
                                                
                if not self.get_user(current_user):
                    return self.create_error_response("User not found", 404)
                
                new_access_token = create_access_token(identity=current_user)

                return jsonify({
                    "access_token": new_access_token
                    }), 200
            
            except Exception:
                return self.create_error_response('An error occurred while processing the request', 500)

    def run_production(self, host: str = '0.0.0.0', port: int = 5000) -> None:
        self.app.run(debug=False, host=host, port=port, use_reloader=False)