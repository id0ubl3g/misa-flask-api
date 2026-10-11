from pika.adapters.blocking_connection import BlockingChannel
from dotenv import load_dotenv
import pika
import os

load_dotenv()

BRIEFING_QUEUE = "briefing_queue"
BRIEFING_DEAD_LETTER_QUEUE = "briefing_queue.dead_letter"

def get_connection() -> pika.BlockingConnection:
    credentials = pika.PlainCredentials(
        username=os.getenv("RABBITMQ_USER", "guest"),
        password=os.getenv("RABBITMQ_PASS", "guest")
    )

    port_env = os.getenv("RABBITMQ_PORT")

    parameters = pika.ConnectionParameters(
        host=os.getenv("RABBITMQ_HOST", "localhost"),
        port=int(port_env) if port_env and port_env.isdigit() else 5672,
        credentials=credentials,
        heartbeat=600,
        blocked_connection_timeout=300
    )

    return pika.BlockingConnection(parameters)

def declare_briefing_queue(channel: BlockingChannel) -> None:
    channel.queue_declare(queue=BRIEFING_DEAD_LETTER_QUEUE, durable=True)

    channel.queue_declare(
        queue=BRIEFING_QUEUE,
        durable=True,
        arguments={
            "x-dead-letter-exchange": "",
            "x-dead-letter-routing-key": BRIEFING_DEAD_LETTER_QUEUE
        }
    )
