from config.path_config import add_project_root_to_path
from dotenv import load_dotenv

load_dotenv()
add_project_root_to_path()

from src.modules.vertex_ai import Vertex

from config.prompt_config import prompt_questions_personalized, prompt_generate_briefing
from config.providers.initialize_mongodb import initialize_mongodb

from src.rabbitmq.connection import get_connection, declare_briefing_queue, BRIEFING_QUEUE
from src.utils.system_utils import parse_ai_json, create_google_credentials

from tenacity import retry, stop_after_attempt, wait_exponential
from pika.exceptions import AMQPConnectionError, AMQPChannelError
from datetime import datetime, timezone
import traceback
import time
import json

QUESTION_KEYS = [f"question {i}" for i in range(1, 6)]

class BriefingWorker:
    def __init__(self) -> None:
        mongo = initialize_mongodb()
        self.clients_collection = mongo["clients_collection"]
        self.vertex = Vertex()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, max=30), reraise=True)
    def generate(self, prompt: str) -> dict:
        response = self.vertex.start_chat(prompt)
        return parse_ai_json(response["data"])

    def validate_personalized_questions(self, questions: dict) -> None:
        for group in ("context_questions", "refinement_questions"):
            group_questions = questions.get(group) if isinstance(questions, dict) else None

            if not isinstance(group_questions, dict):
                raise ValueError(f"Generated questions are missing {group}")

            for key in QUESTION_KEYS:
                if not isinstance(group_questions.get(key), str) or not group_questions[key].strip():
                    raise ValueError(f"Generated questions are missing {group}.{key}")

    def claim_job(self, token: str, stage: str, redelivered: bool) -> bool:
        # A redelivered message means the previous consumer died mid-job, so it may still be marked as processing.
        claimable_statuses = ["queued", "processing"] if redelivered else ["queued"]

        result = self.clients_collection.update_one(
            {"token": token, "job_stage": stage, "job_status": {"$in": claimable_statuses}},
            {"$set": {"job_status": "processing", "job_updated_at": datetime.now(timezone.utc)}}
        )

        return result.matched_count == 1

    def process_initial(self, data: dict) -> None:
        questions = data["questions"]

        merged_prompt = f"{prompt_questions_personalized}{questions}"
        questions_personalized = self.generate(merged_prompt)
        self.validate_personalized_questions(questions_personalized)

        self.clients_collection.update_one(
            {"token": data["token"], "job_stage": "initial", "job_status": "processing"},
            {
                "$set": {
                    "questions": {
                        "initial_questions": questions,
                        "questions_personalized": questions_personalized
                    },
                    "initial_questions_completed": True,
                    "job_status": "done",
                    "job_updated_at": datetime.now(timezone.utc)
                },
                "$unset": {"job_error": ""}
            }
        )

    def process_briefing(self, data: dict) -> None:
        initial_questions = data["initial_questions"]
        context_questions = data["context_questions"]
        refinement_questions = data["refinement_questions"]

        merged_prompt = f"{prompt_generate_briefing}{initial_questions}{context_questions}{refinement_questions}"
        briefing_data = self.generate(merged_prompt)

        if not isinstance(briefing_data, dict):
            raise ValueError("Generated briefing is not a JSON object")

        self.clients_collection.update_one(
            {"token": data["token"], "job_stage": "briefing", "job_status": "processing"},
            {
                "$set": {
                    "questions.questions_personalized.context_questions": context_questions,
                    "questions.questions_personalized.refinement_questions": refinement_questions,
                    "questions_personalized_completed": True,
                    "briefing": True,
                    "briefing_data": briefing_data,
                    "job_status": "done",
                    "job_updated_at": datetime.now(timezone.utc)
                },
                "$unset": {"job_error": ""}
            }
        )

    def callback(self, ch, method, properties, body) -> None:
        token = None
        stage = None

        try:
            data = json.loads(body)
            token = data["token"]
            stage = data["stage"]

            if not self.claim_job(token, stage, method.redelivered):
                print(f"message: Skipping {stage} job for {token}, it is not queued")
                ch.basic_ack(delivery_tag=method.delivery_tag)
                return

            print(f"message: Processing {stage} job for {token}")

            if stage == "initial":
                self.process_initial(data)

            elif stage == "briefing":
                self.process_briefing(data)

            else:
                raise ValueError(f"Unknown stage: {stage}")

            print(f"message: {stage} job for {token} processed successfully")
            ch.basic_ack(delivery_tag=method.delivery_tag)

        except Exception:
            traceback.print_exc()

            if token and stage:
                self.clients_collection.update_one(
                    {"token": token, "job_stage": stage},
                    {
                        "$set": {
                            "job_status": "failed",
                            "job_error": "The AI could not process this briefing. Please submit your answers again.",
                            "job_updated_at": datetime.now(timezone.utc)
                        }
                    }
                )

            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    def execute(self) -> None:
        while True:
            try:
                connection = get_connection()
                channel = connection.channel()
                declare_briefing_queue(channel)
                channel.basic_qos(prefetch_count=1)
                channel.basic_consume(queue=BRIEFING_QUEUE, on_message_callback=self.callback)

                print("Awaiting messages. To exit press CTRL+C")
                channel.start_consuming()

            except (AMQPConnectionError, AMQPChannelError):
                traceback.print_exc()
                print("message: RabbitMQ connection lost, reconnecting in 5 seconds")
                time.sleep(5)

            except KeyboardInterrupt:
                break

if __name__ == "__main__":
    create_google_credentials()
    BriefingWorker().execute()
