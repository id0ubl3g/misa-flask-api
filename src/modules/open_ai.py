from src.utils.return_responses import create_success_return_response

from openai import OpenAI, RateLimitError, AuthenticationError, PermissionDeniedError
from dotenv import load_dotenv
import os

load_dotenv()

class AIServiceUnavailableError(Exception):
    """The provider cannot serve requests until the account is fixed (no credits, revoked key), so retrying now is pointless."""

class OpenAIChat:
    def __init__(self) -> None:
        api_key = os.getenv("OPENAI_API_KEY")

        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")

        self.client = OpenAI(api_key=api_key)
        self.model = os.getenv("OPENAI_MODEL", "gpt-5-mini")

    def start_chat(self, input_text: str) -> dict:
        try:
            response = self.client.responses.create(
                model=self.model,
                input=input_text,
                text={"format": {"type": "json_object"}}
            )

        except RateLimitError as error:
            if error.code == "insufficient_quota":
                raise AIServiceUnavailableError("OpenAI account has no credits remaining. Add credits at https://platform.openai.com/settings/organization/billing") from error

            raise

        except (AuthenticationError, PermissionDeniedError) as error:
            raise AIServiceUnavailableError(f"OpenAI rejected the API key: {error.message}") from error

        return create_success_return_response("Successfully processed the Generative AI response", response.output_text)
