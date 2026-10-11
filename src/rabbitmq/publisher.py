from src.rabbitmq.connection import get_connection, declare_briefing_queue, BRIEFING_QUEUE

import pika
import json

def publish_briefing_job(message: dict) -> None:
    connection = get_connection()

    try:
        channel = connection.channel()
        channel.confirm_delivery()
        declare_briefing_queue(channel)

        channel.basic_publish(
            exchange="",
            routing_key=BRIEFING_QUEUE,
            body=json.dumps(message),
            properties=pika.BasicProperties(
                delivery_mode=pika.DeliveryMode.Persistent,
                content_type="application/json"
            ),
            mandatory=True
        )

    finally:
        connection.close()
