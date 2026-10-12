from src.rabbitmq.publisher import publish_briefing_job

from config.model_questions_personalized import model_questions_personalized
from config.model_initial_questions import model_initial_questions
from config.limits_config import *
from config.input_config import *

from config.providers.initialize_mongodb import initialize_mongodb
from config.providers.initialize_firebase import initialize_firebase
from config.providers.initialize_redis  import initialize_redis
from config.providers.initialize_mercadopago import initialize_mercadopago, REVOKING_STATUSES

from src.utils.system_utils import validate_user_data, is_valid_email

from flask_jwt_extended import JWTManager, create_access_token, create_refresh_token, jwt_required, get_jwt_identity, get_jwt, decode_token, verify_jwt_in_request
from flask import Flask, request, jsonify, Response
from datetime import datetime, timezone, timedelta
from flask_limiter.util import get_remote_address
from pymongo.errors import DuplicateKeyError
from pymongo.collection import Collection
from pymongo import ReturnDocument
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
        redis = initialize_redis(self.app, self.rate_limit_key)
        mercadopago = initialize_mercadopago()

        self.clients_collection: Collection = mongo["clients_collection"]
        self.users_collection: Collection = mongo["users_collection"]
        self.transactions_collection = mongo["transactions_collection"]
        self.usage_events_collection: Collection = mongo["usage_events_collection"]
        
        self.redis_client = redis["redis_client"]
        self.limiter = redis["limiter"]

        @self.jwt.token_in_blocklist_loader
        def is_token_revoked(jwt_header: dict, jwt_payload: dict) -> bool:
            return bool(self.redis_client.exists(f"revoked_token:{jwt_payload['jti']}"))

        self.mercadopago_sdk = mercadopago["mercadopago"]
        self.mercadopago_webhook_secret = mercadopago["webhook_secret"]
        self.plans = mercadopago['plans']

        cors_origins = [origin.strip() for origin in (os.getenv("CORS_ORIGINS") or "*").split(",") if origin.strip()]

        CORS(
            self.app,
            origins=cors_origins,
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
            verify_jwt_in_request(optional=True)

            return get_jwt_identity()

        except Exception:
            return None

    def rate_limit_key(self) -> str:
        for refresh in (False, True):
            try:
                verify_jwt_in_request(refresh=refresh, optional=not refresh)
                identity = get_jwt_identity()

                if identity:
                    return identity

            except Exception:
                continue

        return get_remote_address()

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
                                'misa_payments', 'misa_delete_account', 'misa_refresh_token', 'misa_checkout']

            if endpoint not in (endpoints_require):
                return get_remote_address()
            
            return None

    def check_and_apply_block(self, current_user: str | None, increment: bool = True) -> Response | None:
        if not current_user:
            return None

        block_key = f"blocked:{current_user}"
        count_key = f"count429:{current_user}"

        ttl = self.redis_client.ttl(block_key)
        if ttl > 0:
            minutes = max(1, math.ceil(ttl / 60))
            return self.create_error_response(f"You have been temporarily blocked due to repeated rate limit violations. Please try again in {minutes} minute(s).", 403)

        count =  None

        if increment:
            count = self.redis_client.incr(count_key)

            if count == 1:
                self.redis_client.expire(count_key, 300)

        if increment and count == 3:
            return self.create_error_response("You are approaching the rate limit. One more failed attempt will block you for 30 minutes. Please try again later.", 429)

        if increment and count >= 4:
            self.redis_client.set(block_key, 1, ex=1800)
            self.redis_client.delete(count_key)
            
            return self.create_error_response("You have been temporarily blocked due to repeated rate limit violations.", 403)
        
        return None

    def revoke_token(self, payload: dict) -> None:
        ttl = int(payload["exp"] - datetime.now(timezone.utc).timestamp())

        if ttl > 0:
            self.redis_client.set(f"revoked_token:{payload['jti']}", 1, ex=ttl)

    def get_creation_quota(self, uid: str, plan: str | None, is_active: bool) -> dict:
        now = datetime.now(timezone.utc)
        quota = {}

        for window_name, window in QUOTA_WINDOWS.items():
            limit = CREATION_QUOTAS.get(plan, {}).get(window_name, 0) if is_active else 0
            window_filter = {"uid": uid, "type": "client_created", "created_at": {"$gte": now - window}}

            used = self.usage_events_collection.count_documents(window_filter)
            oldest = self.usage_events_collection.find_one(window_filter, sort=[("created_at", 1)])

            quota[window_name] = {
                "used": used,
                "limit": limit,
                "remaining": max(0, limit - used),
                "resets_at": (oldest["created_at"] + window).isoformat() if oldest else None
            }

        return quota

    def designer_is_active(self, designer_uid: str | None) -> bool:
        if not designer_uid:
            return False

        return not self.user_is_free(designer_uid)

    def verify_mercadopago_signature(self, payment_id: str) -> bool:
        if not self.mercadopago_webhook_secret:
            self.app.logger.error(
                "MERCADOPAGO_WEBHOOK_SECRET is not set: rejecting webhook because its signature cannot be verified."
            )
            return False

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

    def claim_briefing_job(self, client_filter: dict, stage: str) -> dict | None:
        now = datetime.now(timezone.utc)

        return self.clients_collection.find_one_and_update(
            {
                **client_filter,
                "$or": [
                    {"job_status": {"$nin": ["queued", "processing"]}},
                    {"job_updated_at": {"$lt": now - STALE_JOB_AFTER}}
                ]
            },
            {
                "$set": {"job_stage": stage, "job_status": "queued", "job_updated_at": now},
                "$unset": {"job_error": ""}
            },
            return_document=ReturnDocument.AFTER
        )

    def enqueue_briefing_job(self, message: dict) -> bool:
        try:
            publish_briefing_job(message)
            return True

        except Exception:
            self.app.logger.exception("Failed to publish briefing job for %s", message.get("token"))

            self.clients_collection.update_one(
                {"token": message["token"], "job_stage": message["stage"]},
                {
                    "$set": {
                        "job_status": "failed",
                        "job_error": "The briefing service is temporarily unavailable. Please try again in a few minutes.",
                        "job_updated_at": datetime.now(timezone.utc)
                    }
                }
            )

            return False

    def recompute_subscription(self, uid: str) -> dict:
        approved_transactions = self.transactions_collection.find(
            {"uid": uid, "status": "approved"}
        ).sort("approved_at", 1)

        subscription_end = None
        plan = None

        for transaction in approved_transactions:
            approved_at = transaction.get("approved_at")
            transaction_plan = transaction.get("plan")

            if not isinstance(approved_at, datetime) or transaction_plan not in self.plans:
                continue

            if approved_at.tzinfo is None:
                approved_at = approved_at.replace(tzinfo=timezone.utc)

            is_renewal = bool(subscription_end and subscription_end > approved_at)
            period_start = subscription_end if is_renewal else approved_at

            if not is_renewal or STORAGE_LIMITS.get(transaction_plan, 0) >= STORAGE_LIMITS.get(plan, 0):
                plan = transaction_plan

            subscription_end = period_start + timedelta(days=self.plans[transaction_plan]["days"])

        is_active = bool(subscription_end and subscription_end > datetime.now(timezone.utc))

        return {
            "is_free": not is_active,
            "plan": plan if is_active else None,
            "subscription_end": subscription_end if is_active else None
        }

    def _register_routes(self) -> None:
        @self.app.errorhandler(429)
        def ratelimit_error(e) -> Response:
            current_user = self.current_identity()

            response_check_and_apply_block = self.check_and_apply_block(current_user)

            if response_check_and_apply_block:
                return response_check_and_apply_block

            return self.create_error_response("Too many requests. Please try again later.", 429)

        @self.app.route('/health', methods=['GET'])
        @self.limiter.limit("50 per minute")
        def health_check():
            return jsonify({"status": "healthy"}), 200
        
        @self.app.route('/misa/briefing/create_client', methods=['POST'])
        @self.limiter.limit(ABUSE_LIMIT, scope="abuse")
        @jwt_required()
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

                quota = self.get_creation_quota(current_user, current_info_user.get("plan"), True)

                for window_name, window_quota in quota.items():
                    if window_quota["remaining"] <= 0:
                        return jsonify({
                            "error": f"{window_name.capitalize()} client creation quota reached ({window_quota['used']}/{window_quota['limit']}). It resets at {window_quota['resets_at']}.",
                            "quota": quota
                        }), 429

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

                self.usage_events_collection.insert_one({
                    "uid": current_user,
                    "type": "client_created",
                    "token": client_data["token"],
                    "created_at": client_data["created_at"]
                })

                return jsonify({
                    "message": "Client created successfully. Ready to start the brand briefing.",
                    "token": client_data["token"],
                    "usage": {
                        "current_count": current_count + 1,
                        "max_limit": max_limit,
                        "remaining": max_limit - (current_count + 1)
                    },
                    "quota": self.get_creation_quota(current_user, current_info_user.get("plan"), True)
                }), 201
                
            except Exception:
                return self.create_error_response('An error occurred while processing the request', 500)
        
        @self.app.route('/misa/briefing/update_client/<string:token>', methods=['PATCH'])
        @self.limiter.limit("10 per minute")
        @jwt_required()
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

                unknown_fields = set(data.keys()) - UPDATE_CLIENT_FIELDS

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

                try:
                    result = self.clients_collection.update_one({
                        "token": token,
                        "designer_uid": current_user
                        },
                            {
                                "$set": update_data
                            }
                        )

                except DuplicateKeyError:
                    return self.create_error_response("A client with this email already exists.", 409)

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

                claimed_client = self.claim_briefing_job(
                    {"token": token, "initial_questions_completed": False},
                    "initial"
                )

                if not claimed_client:
                    return self.create_error_response('Your answers are already being processed.', 409)

                if not self.enqueue_briefing_job({"token": token, "stage": "initial", "questions": questions}):
                    return self.create_error_response('The briefing service is temporarily unavailable. Please try again in a few minutes.', 503)

                return jsonify({
                    "message": "Brand briefing received successfully. Personalized follow-up questions are being generated.",
                    "status": "queued",
                    "token": token
                }), 202

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

                claimed_client = self.claim_briefing_job(
                    {"token": token, "initial_questions_completed": True, "questions_personalized_completed": False},
                    "briefing"
                )

                if not claimed_client:
                    return self.create_error_response('Your answers are already being processed.', 409)

                job = {
                    "token": token,
                    "stage": "briefing",
                    "initial_questions": initial_questions,
                    "context_questions": data_context_questions,
                    "refinement_questions": data_refinement_questions
                }

                if not self.enqueue_briefing_job(job):
                    return self.create_error_response('The briefing service is temporarily unavailable. Please try again in a few minutes.', 503)

                return jsonify({
                    "message": "Answers received successfully. The brand briefing is being generated.",
                    "status": "queued",
                    "token": token
                }), 202

            except Exception:
                return self.create_error_response('An error occurred while processing the request', 500)

        @self.app.route('/misa/briefing/status/<string:token>', methods=['GET'])
        @self.limiter.limit("60 per minute")
        def misa_briefing_status(token: str) -> Response:
            try:
                validation_error = validate_user_data({"token": token})

                if validation_error:
                    return self.create_error_response(validation_error, 400)

                client = self.clients_collection.find_one({'token': token})

                if not client:
                    return self.create_error_response('Client not found.', 404)

                response = {
                    "token": token,
                    "name_project": client.get("name_project"),
                    "name_client": client.get("name_client"),
                    "designer": client.get("designer"),
                    "designer_active": self.designer_is_active(client.get("designer_uid")),
                    "stage": client.get("job_stage"),
                    "status": client.get("job_status"),
                    "initial_questions_completed": client.get("initial_questions_completed", False),
                    "questions_personalized_completed": client.get("questions_personalized_completed", False)
                }

                if client.get("job_status") == "failed":
                    response["error"] = client.get("job_error")

                if not client.get("initial_questions_completed"):
                    response["initial_questions"] = model_initial_questions["model_initial_questions"]

                if client.get("initial_questions_completed") and not client.get("questions_personalized_completed"):
                    response["questions"] = client["questions"]["questions_personalized"]

                if client.get("briefing"):
                    response["briefing_data"] = client.get("briefing_data")

                return jsonify(response), 200

            except Exception:
                return self.create_error_response('An error occurred while processing the request', 500)

        @self.app.route('/misa/getall_client_responses', methods=['GET'])
        @self.limiter.limit("200 per minute")
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
                        "created_at": response['created_at'],
                        "initial_questions_completed_at": response.get('initial_questions_completed_at'),
                        "briefing_completed_at": response.get('briefing_completed_at')
                    })  

                return jsonify({
                    "message": "Client responses retrieved successfully.",
                    "responses": responses
                }), 200

            except Exception:
                return self.create_error_response('An error occurred while processing the request', 500)

        @self.app.route('/misa/get_client_response/<string:token>', methods=['GET'])
        @self.limiter.limit("200 per minute")
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
        @self.limiter.limit("200 per minute")
        @jwt_required()
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
                data = request.get_json(silent=True)
                token = data.get("token") if isinstance(data, dict) else None

                if not isinstance(token, str) or not token:
                    return self.create_error_response("Token is required", 400)

                try:
                    decoded_token = auth.verify_id_token(token)

                except (ValueError, auth.InvalidIdTokenError, auth.ExpiredIdTokenError, auth.RevokedIdTokenError):
                    return self.create_error_response("Invalid or expired token", 401)

                uid = decoded_token["uid"]
                email = decoded_token["email"]
                name = decoded_token.get("name")
                picture = decoded_token.get("picture")

                user = self.users_collection.find_one({"uid": uid})

                if not user and decoded_token.get("email_verified"):
                    user = self.users_collection.find_one({"email": email})

                    if user:
                        old_uid = user["uid"]
                        self.users_collection.update_one({"_id": user["_id"]}, {"$set": {"uid": uid}})
                        self.clients_collection.update_many({"designer_uid": old_uid}, {"$set": {"designer_uid": uid}})
                        self.transactions_collection.update_many({"uid": old_uid}, {"$set": {"uid": uid}})

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
        @self.limiter.limit("30 per minute")
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

        @self.app.route('/misa/logout', methods=['POST'])
        @self.limiter.limit("20 per minute")
        @jwt_required()
        def misa_logout() -> Response:
            try:
                self.revoke_token(get_jwt())

                data = request.get_json(silent=True)
                refresh_token = data.get("refresh_token") if isinstance(data, dict) else None

                if isinstance(refresh_token, str) and refresh_token:
                    try:
                        refresh_payload = decode_token(refresh_token)

                        if refresh_payload.get("type") == "refresh" and refresh_payload.get("sub") == get_jwt_identity():
                            self.revoke_token(refresh_payload)

                    except Exception:
                        pass

                return jsonify({"message": "Logged out successfully."}), 200

            except Exception:
                return self.create_error_response('An error occurred while processing the request.', 500)

        @self.app.route('/misa/profile', methods=['GET'])
        @self.limiter.limit("200 per minute")
        @jwt_required()
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
                    },
                    "quota": self.get_creation_quota(current_user, current_info_user.get("plan"), not is_free)
                }), 200

            except Exception:
                return self.create_error_response('An error occurred while processing the request.', 500)

        @self.app.route('/misa/payments', methods=['GET'])
        @self.limiter.limit("60 per minute")
        @jwt_required()
        def misa_payments() -> Response:
            try:
                current_user = self.user_or_ip()

                response_check_and_apply_block = self.check_and_apply_block(current_user, increment=False)
                if response_check_and_apply_block:
                    return response_check_and_apply_block

                if not current_user:
                    return self.create_error_response("You are not authorized to access this resource", 401)

                if not self.get_user(current_user):
                    return self.create_error_response("User not found", 404)

                transactions = self.transactions_collection.find(
                    {"uid": current_user},
                    {"_id": 0, "transaction_id": 1, "plan": 1, "amount": 1, "status": 1, "created_at": 1, "approved_at": 1, "refunded_at": 1}
                ).sort("created_at", -1).limit(50)

                payments = [
                    {
                        "id": transaction["transaction_id"][:8],
                        "plan": transaction.get("plan"),
                        "plan_name": self.plans.get(transaction.get("plan"), {}).get("name"),
                        "amount": transaction.get("amount"),
                        "status": transaction.get("status"),
                        "created_at": transaction.get("created_at"),
                        "approved_at": transaction.get("approved_at"),
                        "refunded_at": transaction.get("refunded_at")
                    }
                    for transaction in transactions
                ]

                return jsonify({"payments": payments}), 200

            except Exception:
                return self.create_error_response('An error occurred while processing the request.', 500)

        @self.app.route('/misa/account', methods=['DELETE'])
        @self.limiter.limit("3 per minute")
        @jwt_required()
        def misa_delete_account() -> Response:
            try:
                current_user = self.user_or_ip()

                if not current_user:
                    return self.create_error_response("You are not authorized to access this resource", 401)

                current_info_user = self.get_user(current_user)

                if not current_info_user:
                    return self.create_error_response("User not found", 404)

                data = request.get_json(silent=True)
                confirm_email = data.get("confirm_email") if isinstance(data, dict) else None

                if not isinstance(confirm_email, str) or confirm_email.strip().lower() != (current_info_user.get("email") or "").lower():
                    return self.create_error_response("Type your account email to confirm the deletion.", 400)

                self.clients_collection.delete_many({"designer_uid": current_user})
                self.usage_events_collection.delete_many({"uid": current_user})

                anonymous_uid = "deleted-" + hashlib.sha256(current_user.encode("utf-8")).hexdigest()[:16]
                self.transactions_collection.update_many({"uid": current_user}, {"$set": {"uid": anonymous_uid}})

                self.users_collection.delete_one({"uid": current_user})
                self.revoke_token(get_jwt())

                return jsonify({"message": "Account deleted successfully."}), 200

            except Exception:
                return self.create_error_response('An error occurred while processing the request.', 500)

        @self.app.route('/misa/checkout', methods=['POST'])
        @self.limiter.limit("10 per minute")
        @jwt_required()
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
                preference = preference_response.get("response") or {}

                if preference_response.get("status") not in (200, 201) or not preference.get("init_point"):
                    self.app.logger.error("Mercado Pago preference creation failed: %s", preference_response)
                    self.transactions_collection.delete_one({"transaction_id": transaction_id})

                    return self.create_error_response("Failed to create the checkout with Mercado Pago. Please try again.", 502)

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
            def ignore_notification(reason: str) -> Response:
                self.app.logger.warning("Mercado Pago notification ignored: %s", reason)
                return jsonify({"message": "Notification ignored", "reason": reason}), 200

            try:
                data = request.get_json(silent=True) or {}

                notification_type = data.get("type") or request.args.get("type") or request.args.get("topic")

                if notification_type and notification_type != "payment":
                    return jsonify({"message": "Notification ignored", "type": notification_type}), 200

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
                    return ignore_notification("External reference not found")
                
                parts = external_reference.split(":")

                if len(parts) != 3:
                    return ignore_notification("Invalid external reference")

                uid, plan, transaction_id = parts

                if plan not in self.plans:
                    return ignore_notification("Invalid plan")

                transaction = self.transactions_collection.find_one({"transaction_id": transaction_id})

                if not transaction:
                    return ignore_notification("Transaction not found")

                if transaction.get("uid") != uid or transaction.get("plan") != plan:
                    return ignore_notification("Transaction does not match the payment")

                if status in REVOKING_STATUSES:
                    now = datetime.now(timezone.utc)

                    revoked_transaction = self.transactions_collection.find_one_and_update(
                        {"transaction_id": transaction_id, "status": "approved"},
                        {
                            "$set": {
                                "status": status,
                                "refunded_at": now,
                                "mercadopago_payment_id": str(payment_id)
                            }
                        }
                    )

                    if not revoked_transaction:
                        never_approved = self.transactions_collection.update_one(
                            {"transaction_id": transaction_id, "status": "pending"},
                            {"$set": {"status": status, "mercadopago_payment_id": str(payment_id)}}
                        )

                        if never_approved.matched_count:
                            return jsonify({"message": "Payment was never approved, nothing to revoke", "status": status}), 200

                        return jsonify({"message": "Reversal already processed", "status": status}), 200

                    subscription = self.recompute_subscription(uid)

                    result = self.users_collection.update_one({"uid": uid}, {"$set": subscription})

                    if result.matched_count == 0:
                        return ignore_notification("User not found")

                    self.users_collection.update_one(
                        {"uid": uid, "mercadopago_payment_id": str(payment_id)},
                        {"$unset": {"mercadopago_payment_id": ""}}
                    )

                    still_active = not subscription["is_free"]

                    return jsonify({
                        "message": "Payment reversed and period revoked" if still_active else "Payment reversed and plan revoked",
                        "status": status,
                        "subscription_end": subscription["subscription_end"].isoformat() if still_active else None
                    }), 200

                if status != "approved":
                    return jsonify({
                        "message": "Payment not approved",
                        "status": status
                    }), 200

                if transaction.get("status") != "pending":
                    return jsonify({"message": "Payment already processed", "status": transaction.get("status")}), 200

                current_info_user = self.get_user(uid)

                if not current_info_user:
                    return ignore_notification("User not found")

                expected_price = Decimal(str(self.plans[plan]["price"]))
                paid_price = Decimal(str(payment.get("transaction_amount")))

                if paid_price != expected_price:
                    return ignore_notification("Payment amount does not match the plan price")

                approved_transaction = self.transactions_collection.find_one_and_update(
                    {"transaction_id": transaction_id, "status": "pending"},
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

                if not approved_transaction:
                    return jsonify({"message": "Payment already processed"}), 200

                current_info_user = self.get_user(uid)
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
                self.app.logger.exception("Failed to process Mercado Pago webhook")
                return self.create_error_response('An error occurred while processing the request.', 500)