import pytest
from pydantic import ValidationError

from app.integrations.base import clean_validation_message
from app.integrations.generic_ssh.plugin import GenericSshConfig


def test_clean_validation_message_strips_pydantic_noise() -> None:
    """A pydantic ValidationError's str() is a multi-line dump with a 'For further information visit
    https://errors.pydantic.dev/...' footer - fine in a traceback, not in a form's error banner."""
    with pytest.raises(ValidationError) as exc_info:
        GenericSshConfig.model_validate({"host": "10.0.0.5"})  # device_id missing: must be paired with host

    message = clean_validation_message(exc_info.value)

    assert message == "host and device_id must both be set, or both left unset for a wallet entry"
    assert "https://errors.pydantic.dev" not in message
    assert "Value error" not in message
    assert "\n" not in message


def test_clean_validation_message_falls_back_to_str_for_a_plain_value_error() -> None:
    assert clean_validation_message(ValueError("plain message")) == "plain message"
