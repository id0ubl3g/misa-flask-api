from src.modules.vertex_ai import Vertex

from config.model_questions_personalized import model_questions_personalized
from config.model_initial_questions import model_initial_questions
from config.prompt_config import prompt_questions_personalized, prompt_generate_briefing
from config.limits_config import *
from config.input_config import *

from config.providers.initialize_mongodb import initialize_mongodb
from config.providers.initialize_firebase import initialize_firebase
from config.providers.initialize_redis  import initialize_redis
from config.providers.initialize_mercadopago import initialize_mercadopago, REVOKING_STATUSES

from src.utils.system_utils import parse_ai_json, validate_user_data, is_valid_email

from flask_jwt_extended import JWTManager, create_access_token, create_refresh_token, jwt_required, get_jwt_identity, verify_jwt_in_request
from flask import Flask, request, jsonify, Response
from datetime import datetime, timezone, timedelta
from flask_limiter.util import get_remote_address
from pymongo.errors import DuplicateKeyError
from pymongo.collection import Collection
from firebase_admin import auth
from dotenv import load_dotenv
from flask_cors import CORS
from decimal import Decimal
import secrets
import hashlib
import uuid
import hmac
import math
import os

load_dotenv()

class Server:
    def __init__(self) -> None:
        self.app: Flask = Flask(__name__)

        self.app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY')
        self.app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=1)
        self.app.config['JWT_REFRESH_TOKEN_EXPIRES'] = timedelta(days=30)
        self.app.config['RATELIMIT_STORAGE_URI'] = os.getenv("REDIS_URL")
        self.app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024

        self.jwt: JWTManager = JWTManager(self.app)

        mongo = initialize_mongodb()
        initialize_firebase()
        redis = initialize_redis(self.app, self.user_or_ip)
        mercadopago = initialize_mercadopago()

        self.clients_collection: Collection = mongo["clients_collection"]
        self.users_collection: Collection = mongo["users_collection"]
        self.transactions_collection = mongo["transactions_collection"]
        
        self.redis_client = redis["redis_client"]
        self.limiter = redis["limiter"]

        self.mercadopago_sdk = mercadopago["mercadopago"]
        self.mercadopago_webhook_secret = mercadopago["webhook_secret"]
        self.plans = mercadopago['plans']

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

    def user_is_free(self, uid: str) -> bool:
        current_user = self.get_user(uid)

        if not current_user:
            return True

        subscription_end = current_user.get("subscription_end")
        has_active_subscription = False

        if isinstance(subscription_end, datetime):
            if subscription_end.tzinfo is None:
                subscription_end = subscription_end.replace(tzinfo=timezone.utc)
                
            has_active_subscription = datetime.now(timezone.utc) < subscription_end

        if has_active_subscription:
            if current_user.get("is_free", True):
                self.users_collection.update_one(
                    {"uid": uid},
                    {"$set": {"is_free": False}}
                )
            return False

        if not current_user.get("is_free", True):
            self.users_collection.update_one(
                {"uid": uid},
                {"$set": {"is_free": True}}
            )

        return True

    def current_identity(self) -> str | None:
        try:
            return get_jwt_identity()

        except Exception:
            return None

    def user_or_ip(self) -> str | None:
        try:
            verify_jwt_in_request()
            identity = get_jwt_identity()
            if identity:
                return identity
            
        except Exception:
            endpoint = request.endpoint
            endpoints_require = ['misa_briefing_create_client', 'misa_briefing_update_client',
                                'misa_getall_client_responses', 'misa_get_client_response_by_token',
                                'misa_delete_client_response_by_token', 'misa_profile', 
                                'misa_metrics', 'misa_refresh_token', 'misa_checkout']

            if endpoint not in (endpoints_require):
                return get_remote_address()
            
            return None

    def check_and_apply_block(self, current_user: str, increment: bool = True) -> Response | None:
        block_key = f"blocked:{current_user}"
        count_key = f"count429:{current_user}"
        
        ttl = self.redis_client.ttl(block_key)
        if ttl > 0:
            minutes = max(1, math.ceil(ttl / 60))
            return self.create_error_response(f"You have been temporarily blocked due to repeated rate limit violations. Please try again in {minutes} minute(s).", 403)
        
        count =  None
        
        if increment:
            pipe = self.redis_client.pipeline()
            pipe.incr(count_key)
            pipe.expire(count_key, 300)
            
            count, _ = pipe.execute()

        if increment and count == 3:
            return self.create_error_response("You are approaching the rate limit. One more failed attempt will block you for 30 minutes. Please try again later.", 429)

        if increment and count >= 4:
            self.redis_client.set(block_key, 1, ex=1800)
            self.redis_client.delete(count_key)
            
            return self.create_error_response("You have been temporarily blocked due to repeated rate limit violations.", 403)
        
        return None

    def get_dynamic_limit(self) -> str:
        current_user = self.current_identity()

        if not current_user or self.user_is_free(current_user):
            return ABUSE_LIMIT

        user_info = self.get_user(current_user) or {}
        plan = user_info.get("plan")

        return PLAN_LIMITS.get(plan, ABUSE_LIMIT)

    def designer_is_active(self, designer_uid: str | None) -> bool:
        if not designer_uid:
            return False

        return not self.user_is_free(designer_uid)

    def verify_mercadopago_signature(self, payment_id: str) -> bool:
        if not self.mercadopago_webhook_secret:
            self.app.logger.warning(
                "MERCADOPAGO_WEBHOOK_SECRET is not set: webhook signatures are not being verified."
            )
            return True

        signature = request.headers.get("x-signature", "")
        request_id = request.headers.get("x-request-id", "")

        parts = dict(
            piece.split("=", 1) for piece in signature.split(",") if "=" in piece
        )

        ts = parts.get("ts", "").strip()
        received_signature = parts.get("v1", "").strip()

        if not ts or not received_signature:
            return False

        data_id = str(payment_id)

        if data_id.isalnum():
            data_id = data_id.lower()

        manifest = f"id:{data_id};"

        if request_id:
            manifest += f"request-id:{request_id};"

        manifest += f"ts:{ts};"

        expected_signature = hmac.new(
            self.mercadopago_webhook_secret.encode("utf-8"),
            manifest.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(expected_signature, received_signature)

    def check_client_limit_storage(self, uid: str, user_info: dict) -> tuple[bool, int, int]:
        is_active = not self.user_is_free(uid)
        plan = user_info.get("plan")

        max_limit = STORAGE_LIMITS.get(plan, 0) if is_active else 0
        current_count = self.clients_collection.count_documents({
            "designer_uid": uid
        })

        return current_count < max_limit, current_count, max_limit

    def _register_routes(self) -> None:
        @self.app.errorhandler(429)
        def ratelimit_error(e) -> Response:
            current_user = self.current_identity()

            if not current_user:
                return self.create_error_response("Too many requests. Please try again later.", 429)

            response_check_and_apply_block = self.check_and_apply_block(current_user)

            if response_check_and_apply_block:
                return response_check_and_apply_block

            breached = getattr(self.limiter, "current_limit", None)

            if request.endpoint == "misa_briefing_create_client" and breached and "month" in str(breached.limit):
                return self.create_error_response("Monthly client creation quota reached for your plan. Upgrade your plan to continue using this feature.", 429)

            return self.create_error_response("Too many requests. Please try again later.", 429)

        @self.app.route('/health', methods=['GET'])
        @self.limiter.limit("50 per minute")
        def health_check():
            return jsonify({"status": "healthy"}), 200
        
        @self.app.route('/misa/briefing/create_client', methods=['POST'])
        @jwt_required()
        @self.limiter.limit(ABUSE_LIMIT)
        @self.limiter.limit(self.get_dynamic_limit, deduct_when=lambda response: response.status_code == 201)
        def misa_briefing_create_client() -> Response:
            try:
                current_user = self.user_or_ip()

                if not current_user:
                    return self.create_error_response("You are not authorized to access this resource", 401)

                current_info_user = self.get_user(current_user)

                if not current_info_user:
                    return self.create_error_response("User not found", 404)

                if self.user_is_free(current_user):
                    return self.create_error_response("An active subscription is required to create clients. Please subscribe to a plan to continue.", 402)

                allowed, current_count, max_limit = self.check_client_limit_storage(current_info_user.get('uid'), current_info_user)

                if not allowed:
                    return self.create_error_response(f"Client creation blocked. Limit reached ({current_count}/{max_limit}).", 403)

                data = request.get_json()

                if not isinstance(data, dict):
                    return self.create_error_response("Request body must be a JSON object", 400)

                if not data:
                    return self.create_error_response('No data provided', 400)

                unknown_fields = set(data.keys()) - ALLOWED_FIELDS

                if unknown_fields:
                    return self.create_error_response(f"Disallowed fields found: {', '.join(unknown_fields)}", 400)

                name_project = data.get('name_project')
                name_client = data.get('name_client')
                email_client = data.get('email_client')

                if not isinstance(name_project, str):
                    return self.create_error_response("Name project must be a string", 400)

                if not isinstance(name_client, str):
                    return self.create_error_response("Name client must be a string", 400)

                if not isinstance(email_client, str):
                    return self.create_error_response("Email client must be a string", 400)

                if not name_project or not name_client or not email_client:
                    return self.create_error_response(f'Missing required fields: {", ".join(["name_project", "name_client", "email_client"])}', 400)

                email_client = email_client.strip().lower()

                if not is_valid_email(email_client):
                    return self.create_error_response('Invalid email format', 400)

                client_exists = self.clients_collection.find_one({
                    'designer_uid': current_info_user['uid'],
                    'email_client': email_client
                })

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

                try:
                    self.clients_collection.insert_one(client_data)

                except DuplicateKeyError:
                    return self.create_error_response('A client with this email already exists.', 400)

                return jsonify({
                    "message": "Client created successfully. Ready to start the brand briefing.",
                    "token": client_data["token"],
                    "usage": {
                        "current_count": current_count + 1,
                        "max_limit": max_limit,
                        "remaining": max_limit - (current_count + 1)
                    }
                }), 201
                
            except Exception:
                return self.create_error_response('An error occurred while processing the request', 500)
        
        @self.app.route('/misa/briefing/update_client/<string:token>', methods=['PATCH'])
        @jwt_required()
        @self.limiter.limit("10 per minute")
        def misa_briefing_update_client(token: str) -> Response:
            try:
                current_user = self.user_or_ip()

                if not current_user:
                    return self.create_error_response("You are not authorized to access this resource", 401)

                current_info_user = self.get_user(current_user)

                if not current_info_user:
                    return self.create_error_response("User not found", 404)

                data = request.get_json()

                if not isinstance(data, dict):
                    return self.create_error_response("Request body must be a JSON object", 400)

                if not data:
                    return self.create_error_response("No data provided", 400)

                unknown_fields = set(data.keys()) - ALLOWED_FIELDS

                if unknown_fields:
                    return self.create_error_response(f"Disallowed fields found: {', '.join(sorted(unknown_fields))}", 400)

                current_client = self.clients_collection.find_one({"token": token})

                if not current_client:
                    return self.create_error_response("Client not found", 404)

                update_data = {}

                for field, value in data.items():
                    if not isinstance(value, str):
                        return self.create_error_response(f"{field} must be a string", 400)

                    value = value.strip()

                    if not value:
                        return self.create_error_response(f"{field} cannot be empty", 400)

                    update_data[field] = value

                if "email_client" in update_data:
                    email_client = update_data["email_client"].lower()

                    if not is_valid_email(email_client):
                        return self.create_error_response("Invalid email format", 400)

                    update_data["email_client"] = email_client

                if "name_project" in update_data or "name_client" in update_data:
                    validation_data = {}

                    if "name_project" in update_data:
                        validation_data["name_project"] = update_data["name_project"]

                    if "name_client" in update_data:
                        validation_data["name_client"] = update_data["name_client"]

                    validation_error = validate_user_data(validation_data)

                    if validation_error:
                        return self.create_error_response(validation_error, 400)

                if not update_data:
                    return self.create_error_response("No fields to update", 400)

                result = self.clients_collection.update_one({
                    "token": token, 
                    "designer_uid": current_user
                    }, 
                        {
                            "$set": update_data
                        }
                    )

                if result.matched_count == 0:
                    return self.create_error_response("Client not found", 404)

                return jsonify({
                    "message": "Client updated successfully",
                    "updated_fields": list(update_data.keys()),
                    "modified": result.modified_count > 0
                }), 200

            except Exception:
                return self.create_error_response("An error occurred while processing the request", 500)

        @self.app.route('/misa/briefing/ping_client_response/<string:token>', methods=['POST'])
        @self.limiter.limit("5 per minute")
        def misa_briefing_ping_client_response(token: str) -> Response:
            try:
                data = request.get_json()

                if not isinstance(data, dict):
                    return self.create_error_response("Request body must be a JSON object", 400)

                if not data:
                    return self.create_error_response('No data provided', 400)

                unknown_fields = set(data.keys()) - ALLOWED_FIELDS

                if unknown_fields:
                    return self.create_error_response(f"Disallowed fields found: {', '.join(unknown_fields)}", 400)

                initial_questions = data.get('model_initial_questions')

                if initial_questions is not None and not isinstance(initial_questions, bool):
                    return {"error": "Initial questions must be a boolean"}, 400
                
                if initial_questions is True:
                    return jsonify(model_initial_questions), 200

                business = data.get('business')
                target_audience = data.get('target_audience')
                objective = data.get('objective')
                differential = data.get('differential')
                personality = data.get('personality')

                if not business or not target_audience or not objective or not differential or not personality:
                    return self.create_error_response(f'Missing required fields: {", ".join(["business", "target_audience", "objective", "differential", "personality"])}', 400)

                fields = {
                    "business": business,
                    "target_audience": target_audience,
                    "objective": objective,
                    "differential": differential,
                    "personality": personality
                }

                for field, value in fields.items():
                    if not isinstance(value, str):
                        return {"error": f"{field.replace('_', ' ').capitalize()} must be a string"}, 400

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

                if not self.designer_is_active(client_exists.get('designer_uid')):
                    return self.create_error_response('This briefing is unavailable because the designer does not have an active subscription.', 403)

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
                response_generative_ai = Vertex().start_chat(merged_prompt)
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
        @self.limiter.limit("5 per minute")
        def misa_briefing_pong_client_response(token: str) -> Response:
            try:
                data = request.get_json()

                if not isinstance(data, dict):
                    return self.create_error_response("Request body must be a JSON object", 400)

                if not data:
                    return self.create_error_response('No data provided', 400)

                unknown_fields = set(data.keys()) - ALLOWED_FIELDS

                if unknown_fields:
                    return self.create_error_response(f"Disallowed fields found: {', '.join(unknown_fields)}", 400)

                questions_personalized = data.get('model_questions_personalized')

                if questions_personalized is not None and not isinstance(questions_personalized, bool):
                    return {"error": "Initial personalized must be a boolean"}, 400
                
                if questions_personalized is True:
                    return jsonify(model_questions_personalized), 200

                current_info_client = self.clients_collection.find_one({'token': token})
                if not current_info_client:
                    return self.create_error_response('Client not found.', 404)

                if not self.designer_is_active(current_info_client.get('designer_uid')):
                    return self.create_error_response('This briefing is unavailable because the designer does not have an active subscription.', 403)

                if not current_info_client.get('initial_questions_completed'):
                    return self.create_error_response('Initial questions have not been completed yet.', 400)

                if current_info_client.get('questions_personalized_completed'):
                    return self.create_error_response('Questions personalized have already been completed.', 400)

                context_questions = data.get('context_questions')
                refinement_questions = data.get('refinement_questions')

                if context_questions is None:
                    return self.create_error_response("Missing required field: context_questions", 400)

                if refinement_questions is None:
                    return self.create_error_response("Missing required field: refinement_questions", 400)

                if not isinstance(context_questions, dict):
                    return self.create_error_response("context_questions must be an object", 400)

                if not isinstance(refinement_questions, dict):
                    return self.create_error_response("refinement_questions must be an object", 400)

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

                    if not isinstance(answer, str):
                        return {"error": "Question answer must be a string"}, 400

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

                    if not isinstance(answer, str):
                        return {"error": "Question answer must be a string"}, 400

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
                response_generative_ai = Vertex().start_chat(merged_prompt)
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
        @self.limiter.limit("200 per minute")
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
        @self.limiter.limit("200 per minute")
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

                if not client_response:
                    return self.create_error_response("Client response not found", 404)

                client_response["_id"] = str(client_response["_id"])

                return jsonify({
                    "message": "Client response retrieved successfully.",
                    "response": client_response
                }), 200

            except Exception:
                return self.create_error_response('An error occurred while processing the request', 500)

        @self.app.route('/misa/delete_client_response/<string:token>', methods=['DELETE'])
        @jwt_required()
        @self.limiter.limit("200 per minute")
        def misa_delete_client_response_by_token(token: str) -> Response:
            try:
                current_user = self.user_or_ip()

                if not current_user:
                    return self.create_error_response("You are not authorized to access this resource", 401)

                current_info_user = self.get_user(current_user)

                if not current_info_user:
                    return self.create_error_response("User not found", 404)

                result = self.clients_collection.delete_one({
                    "designer_uid": current_info_user['uid'],
                    "token": token
                })

                if result.deleted_count == 0:
                    return self.create_error_response("Client response not found", 404)

                return jsonify({"message": "Client response deleted successfully",}), 200

            except Exception:
                return self.create_error_response('An error occurred while processing the request', 500)

        @self.app.route("/misa/auth/google", methods=["POST"])
        @self.limiter.limit("10 per minute")
        def misa_auth_google():
            try:
                token = request.json.get("token")
                decoded_token = auth.verify_id_token(token)

                uid = decoded_token["uid"]
                email = decoded_token["email"]
                name = decoded_token.get("name")
                picture = decoded_token.get("picture")

                user = self.users_collection.find_one({"uid": uid})

                access_token = create_access_token(identity=uid)
                refresh_token = create_refresh_token(identity=uid)
                
                if not user:
                    self.users_collection.insert_one({
                        "uid": uid,
                        "email": email,
                        "name": name,
                        "picture": picture,
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
                            "name": name,
                            "picture": picture
                        }
                    }), 201

                return jsonify({
                    "message": "Authentication completed successfully.", 
                    "new_user": False,
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "user": {
                        "email": email,
                        "name": name,
                        "picture": picture
                    }
                }), 200

            except Exception:
                return self.create_error_response('An error occurred while processing the request', 500)

        @self.app.route('/misa/refresh_token', methods=['POST'])
        @jwt_required(refresh=True)
        @self.limiter.limit("5 per minute")
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

        @self.app.route('/misa/profile', methods=['GET'])
        @jwt_required()
        @self.limiter.limit("200 per minute")
        def misa_profile() -> Response:
            try:
                current_user = self.user_or_ip()
                
                response_check_and_apply_block = self.check_and_apply_block(current_user, increment=False)
                if response_check_and_apply_block:
                    return response_check_and_apply_block
                
                if not current_user:
                    return self.create_error_response("You are not authorized to access this resource", 401)

                current_info_user = self.get_user(current_user)

                if not current_info_user:
                    return self.create_error_response("User not found", 404)

                is_free = self.user_is_free(current_user)
                _, current_count, max_limit = self.check_client_limit_storage(current_user, current_info_user)

                return jsonify({
                    "uid": current_info_user.get("uid"),
                    "email": current_info_user.get("email"),
                    "name": current_info_user.get("name"),
                    "picture": current_info_user.get("picture"),
                    "is_free": is_free,
                    "plan": None if is_free else current_info_user.get("plan"),
                    "subscription_end": current_info_user.get("subscription_end"),
                    "created_at": current_info_user.get("created_at"),
                    "usage": {
                        "current_count": current_count,
                        "max_limit": max_limit,
                        "remaining": max(0, max_limit - current_count)
                    }
                }), 200

            except Exception:
                return self.create_error_response('An error occurred while processing the request.', 500)

        @self.app.route('/misa/metrics', methods=['GET'])
        @jwt_required()
        @self.limiter.limit("200 per minute")
        def misa_metrics() -> Response:
            try:    
                current_user = self.user_or_ip()
                
                response_check_and_apply_block = self.check_and_apply_block(current_user, increment=False)
                if response_check_and_apply_block:
                    return response_check_and_apply_block
                
                if not current_user:
                    return self.create_error_response("You are not authorized to access this resource", 401)

                current_info_user = self.get_user(current_user)
                
                if not current_info_user:
                    return self.create_error_response("User not found", 404)

                designer_uid = current_info_user['uid']

                clients = self.clients_collection.count_documents({
                    "designer_uid": designer_uid
                })
                briefing = self.clients_collection.count_documents({
                    "designer_uid": designer_uid,
                    "briefing": True
                })
                pending = self.clients_collection.count_documents({
                    "designer_uid": designer_uid,
                    "briefing": False
                })

                return jsonify({"clients": clients, "briefing": briefing, "pending": pending}), 200

            except Exception:
                return self.create_error_response('An error occurred while processing the request.', 500)

        @self.app.route('/misa/checkout', methods=['POST'])
        @jwt_required()
        @self.limiter.limit("10 per minute")
        def misa_checkout() -> Response:
            try:
                current_user = self.user_or_ip()
                
                response_check_and_apply_block = self.check_and_apply_block(current_user, increment=False)
                if response_check_and_apply_block:
                    return response_check_and_apply_block
                
                if not current_user:
                    return self.create_error_response("You are not authorized to access this resource", 401)

                current_info_user = self.get_user(current_user)
                
                if not current_info_user:
                    return self.create_error_response("User not found", 404)
                
                data = request.get_json()

                if not isinstance(data, dict):
                    return self.create_error_response("Request body must be a JSON object", 400)

                if not data:
                    return self.create_error_response('No data provided', 400)

                unknown_fields = set(data.keys()) - ALLOWED_FIELDS

                if unknown_fields:
                    return self.create_error_response(f"Disallowed fields found: {', '.join(unknown_fields)}", 400)

                plan = data.get("plan")
                success_url = data.get("success_url")
                failure_url = data.get("failure_url")
                pending_url = data.get("pending_url")

                fields = {
                    "plan": plan,
                    "success_url": success_url,
                    "failure_url": failure_url,
                    "pending_url": pending_url
                }

                for field, value in fields.items():
                    if not isinstance(value, str):
                        return self.create_error_response(
                            f"{field} must be a string", 400)

                plan = fields["plan"].strip().lower()
                success_url = fields["success_url"].strip()
                failure_url = fields["failure_url"].strip()
                pending_url = fields["pending_url"].strip()

                if not plan or plan not in self.plans:
                    return self.create_error_response("Plan is required", 400)
                
                if not success_url or not failure_url or not pending_url:
                    return self.create_error_response("Success, failure and pending URLs are required", 400)

                validation_error = validate_user_data({
                    "success_url": success_url,
                    "failure_url": failure_url,
                    "pending_url": pending_url
                })

                if validation_error:
                    return self.create_error_response(validation_error, 400)

                selected_plan = self.plans.get(plan)
                price = selected_plan['price']
                email = current_info_user['email']

                if not email:
                    return self.create_error_response("No email address found for this account", 404)

                transaction_id = str(uuid.uuid4())
                now = datetime.now(timezone.utc)
                
                self.transactions_collection.insert_one({
                    "transaction_id": transaction_id,
                    "uid": current_user,
                    "plan": plan,
                    "amount": price,
                    "status": "pending",
                    "mercadopago_payment_id": None,
                    "created_at": now,
                    "expires_at": now + timedelta(days=30)
                })

                preference_data = {
                    "items": [
                        {
                            "title": "Misa Premium",
                            "quantity": 1,
                            "unit_price": price,
                            "currency_id": "BRL"
                        }
                    ],
                    "payer": {
                        "email": email
                    },
                    "external_reference": f"{current_user}:{plan}:{transaction_id}",
                    "back_urls": {
                        "success": success_url,
                        "failure": failure_url,
                        "pending": pending_url
                    },
                    "auto_return": "approved"
                }

                preference_response = self.mercadopago_sdk.preference().create(preference_data)
                preference = preference_response["response"]

                self.transactions_collection.update_one(
                    {"transaction_id": transaction_id},
                    {
                        "$set": {
                            "preference_id": str(preference["id"]),
                            "checkout_url": preference["init_point"]
                        }
                    }
                )
            
                return jsonify({'checkout_url': preference["init_point"]}), 200

            except Exception:
                return self.create_error_response('An error occurred while processing the request.', 500)

        @self.app.route('/misa/webhook', methods=['POST'])
        def misa_webhook() -> Response:
            try:
                data = request.get_json(silent=True) or {}

                payment_id = (
                    data.get("data", {}).get("id")
                    or request.args.get("data.id")
                )

                if not payment_id:
                    return self.create_error_response("Payment ID not found", 400)

                if not self.verify_mercadopago_signature(payment_id):
                    return self.create_error_response("Invalid webhook signature", 401)

                payment_response = self.mercadopago_sdk.payment().get(payment_id)

                if payment_response["status"] != 200:
                    return self.create_error_response('Failed to retrieve payment information from Mercado Pago.', 400)

                payment = payment_response["response"]
                status = payment.get("status")

                external_reference = payment.get("external_reference")

                if not external_reference:
                    return self.create_error_response("External reference not found", 400)
                
                parts = external_reference.split(":")

                if len(parts) != 3:
                    return self.create_error_response("Invalid external reference", 400)

                uid, plan, transaction_id = parts

                if plan not in self.plans:
                    return self.create_error_response("Invalid plan", 400)

                transaction = self.transactions_collection.find_one({"transaction_id": transaction_id})

                if not transaction:
                    return self.create_error_response("Transaction not found", 404)

                if transaction.get("uid") != uid or transaction.get("plan") != plan:
                    return self.create_error_response("Transaction does not match the payment", 400)

                if status in REVOKING_STATUSES:
                    if transaction.get("status") in REVOKING_STATUSES:
                        return jsonify({"message": "Reversal already processed", "status": transaction.get("status")}), 200

                    self.transactions_collection.update_one(
                        {"transaction_id": transaction_id},
                        {
                            "$set": {
                                "status": status,
                                "refunded_at": datetime.now(timezone.utc),
                                "mercadopago_payment_id": str(payment_id)
                            }
                        }
                    )

                    refunded_user = self.get_user(uid)

                    if not refunded_user:
                        return self.create_error_response("User not found", 404)

                    now = datetime.now(timezone.utc)
                    subscription_end = refunded_user.get("subscription_end")

                    if isinstance(subscription_end, datetime):
                        if subscription_end.tzinfo is None:
                            subscription_end = subscription_end.replace(tzinfo=timezone.utc)
                    else:
                        subscription_end = None

                    if subscription_end:
                        subscription_end -= timedelta(days=self.plans[plan]["days"])

                    still_active = bool(subscription_end and subscription_end > now)

                    update_user = {
                        "$set": {
                            "is_free": not still_active,
                            "plan": refunded_user.get("plan") if still_active else None,
                            "subscription_end": subscription_end if still_active else None
                        }
                    }

                    if refunded_user.get("mercadopago_payment_id") == str(payment_id):
                        update_user["$unset"] = {"mercadopago_payment_id": ""}

                    self.users_collection.update_one({"uid": uid}, update_user)

                    return jsonify({
                        "message": "Payment reversed and period revoked" if still_active else "Payment reversed and plan revoked",
                        "status": status,
                        "subscription_end": subscription_end.isoformat() if still_active else None
                    }), 200

                if status != "approved":
                    return jsonify({
                        "message": "Payment not approved",
                        "status": status
                    }), 200

                if transaction.get("status") == "approved":
                    return jsonify({"message": "Payment already processed"}), 200

                current_info_user = self.get_user(uid)

                if not current_info_user:
                    return self.create_error_response("User not found", 404)

                expected_price = Decimal(str(self.plans[plan]["price"]))
                paid_price = Decimal(str(payment.get("transaction_amount")))

                if paid_price != expected_price:
                    return self.create_error_response("Payment amount does not match the plan price", 400)

                selected_plan = self.plans[plan]

                now = datetime.now(timezone.utc)
                current_subscription_end = current_info_user.get("subscription_end")

                if isinstance(current_subscription_end, datetime):
                    if current_subscription_end.tzinfo is None:
                        current_subscription_end = current_subscription_end.replace(tzinfo=timezone.utc)
                else:
                    current_subscription_end = None

                subscription_is_active = bool(current_subscription_end and current_subscription_end > now)

                subscription_start = current_subscription_end if subscription_is_active else now
                subscription_end = subscription_start + timedelta(days=selected_plan["days"])

                current_plan = current_info_user.get("plan") if subscription_is_active else None
                effective_plan = plan

                if current_plan and STORAGE_LIMITS.get(current_plan, 0) > STORAGE_LIMITS.get(plan, 0):
                    effective_plan = current_plan

                self.transactions_collection.update_one(
                    {"transaction_id": transaction_id},
                    {
                        "$set": {
                            "status": "approved",
                            "mercadopago_payment_id": str(payment_id),
                            "approved_at": datetime.now(timezone.utc)
                        },
                        "$unset": {
                            "expires_at": ""
                        }
                    }
                )
                
                self.users_collection.update_one(
                    {"uid": uid},
                    {
                        "$set": {
                            "is_free": False,
                            "plan": effective_plan,
                            "subscription_end": subscription_end,
                            "mercadopago_payment_id": str(payment_id),
                        }
                    }
                )
        
                return jsonify({
                    "message": "Payment approved and plan renewed" if subscription_is_active else "Payment approved and plan activated",
                    "status": "approved",
                    "plan": effective_plan,
                    "subscription_end": subscription_end.isoformat()
                }), 200

            except Exception:
                return self.create_error_response('An error occurred while processing the request.', 500)