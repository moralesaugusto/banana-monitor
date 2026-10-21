"""Which model server an agent talks to: Ollama (no key) or OpenRouter (API key from the credential store)."""

from dataclasses import dataclass

from app.config import get_settings
from app.credentials.crypto import get_secret_box
from app.credentials.service import CredentialNotFoundError, CredentialService
from app.db.session import Databases
from app.domain.enums import AssistantProvider
from app.domain.models import AiModeSettings
from app.llm.client import LLMRequestError

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


@dataclass
class Endpoint:
    provider: AssistantProvider
    base_url: str
    model: str
    credential_id: int | None


def effective_endpoint(
    defaults: AiModeSettings, *, provider: str, base_url: str, model: str, credential_id: int | None
) -> Endpoint:
    """An agent's own provider, host, model and key where it sets them, else the AI Mode defaults. An
    agent on a different provider than the default cannot reuse the default's host or model name."""
    chosen = AssistantProvider(provider) if provider else defaults.llm_provider
    if chosen == defaults.llm_provider:
        host, name = base_url or defaults.llm_base_url, model or defaults.llm_model
    else:
        is_openrouter = chosen == AssistantProvider.OPENROUTER
        standard = OPENROUTER_BASE_URL if is_openrouter else get_settings().ollama_base_url
        host, name = base_url or standard, model
    key_id = None
    if chosen == AssistantProvider.OPENROUTER:
        key_id = credential_id or defaults.llm_credential_id
    return Endpoint(chosen, host, name, key_id)


async def load_api_key(databases: Databases, credential_id: int | None) -> str | None:
    """The decrypted OpenRouter key, for the caller to keep in a local variable only."""
    if credential_id is None:
        return None
    async with databases.credentials_session_factory() as session:
        try:
            secret = await CredentialService(get_secret_box()).get_decrypted(session, credential_id)
        except CredentialNotFoundError as exc:
            raise LLMRequestError("The OpenRouter API key credential no longer exists") from exc
    token = secret.get("token")
    return token if isinstance(token, str) and token else None
