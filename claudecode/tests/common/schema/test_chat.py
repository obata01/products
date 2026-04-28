import pytest
from pydantic import ValidationError

from src.common.schema.chat import ChatRequest


class TestChatRequestSessionId:
    """ChatRequest.session_id の UUID 検証."""

    @pytest.mark.parametrize(
        "valid_uuid",
        [
            "550e8400-e29b-41d4-a716-446655440000",
            "00000000-0000-0000-0000-000000000000",
            "bd3b25c7-6a29-4e9d-8f9a-7b8a5f3c1d2e",
        ],
    )
    def test_accepts_valid_uuid(self, valid_uuid: str) -> None:
        req = ChatRequest(session_id=valid_uuid, message="hi")
        assert req.session_id == valid_uuid

    def test_accepts_none(self) -> None:
        req = ChatRequest(session_id=None, message="hi")
        assert req.session_id is None

    def test_defaults_to_none(self) -> None:
        req = ChatRequest(message="hi")
        assert req.session_id is None

    @pytest.mark.parametrize(
        "invalid_value",
        [
            "not-a-uuid",
            "test-api",
            "123",
            "",
            "550e8400-e29b-41d4-a716",
        ],
    )
    def test_rejects_non_uuid(self, invalid_value: str) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ChatRequest(session_id=invalid_value, message="hi")
        assert "session_id must be a valid UUID string" in str(exc_info.value)
