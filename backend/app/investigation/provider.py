"""The model-provider boundary. Everything behind diagnose() is
swappable; everything in front of it (validation, catalogue filtering,
state transitions) never trusts what comes back.
"""

from app.config import settings
from app.investigation.schema import Diagnosis


class ProviderError(Exception):
    pass


class SchemaError(Exception):
    def __init__(self, raw: str):
        self.raw = raw
        super().__init__("model output failed schema validation")


class AnthropicProvider:
    def __init__(self):
        from anthropic import Anthropic

        self.model = settings.ai_model
        self.client = Anthropic(
            api_key=settings.anthropic_api_key, timeout=settings.ai_timeout_seconds
        )

    def diagnose(self, system: str, evidence: str) -> tuple[dict, dict, str]:
        """Returns (diagnosis dict, usage, raw text)."""
        import anthropic

        try:
            response = self.client.messages.parse(
                model=self.model,
                max_tokens=settings.ai_max_output_tokens,
                thinking={"type": "adaptive"},
                system=system,
                messages=[{"role": "user", "content": evidence}],
                output_format=Diagnosis,
            )
        except anthropic.APIError as exc:
            raise ProviderError(str(exc)) from exc

        raw = next((b.text for b in response.content if b.type == "text"), "")
        if response.parsed_output is None:
            raise SchemaError(raw)
        usage = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        }
        return response.parsed_output.model_dump(), usage, raw


def get_provider() -> AnthropicProvider | None:
    if not settings.anthropic_api_key:
        return None
    return AnthropicProvider()
