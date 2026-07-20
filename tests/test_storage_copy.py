import asyncio

import pytest

from komuzik.storage import PartialCopyError, copy_messages_to_chat


class FakeMsg:
    def __init__(self, media_id: int, text: str = ""):
        self.media = media_id
        self.message = text


class FakeClient:
    def __init__(self, fail_at: int | None = None):
        self.fail_at = fail_at
        self.sent: list[tuple[int, object, str]] = []
        self._attempt = 0

    async def send_file(self, dest_chat_id: int, media, *, caption: str = ""):
        self._attempt += 1
        if self.fail_at is not None and self._attempt == self.fail_at:
            raise RuntimeError(f"fail at {self.fail_at}")
        self.sent.append((dest_chat_id, media, caption))


def test_copy_messages_all_ok():
    client = FakeClient()
    msgs = [FakeMsg(1), FakeMsg(2)]
    n = asyncio.run(copy_messages_to_chat(client, 42, msgs))
    assert n == 2
    assert len(client.sent) == 2


def test_partial_copy_error_sent_count():
    client = FakeClient(fail_at=2)
    msgs = [FakeMsg(1), FakeMsg(2), FakeMsg(3)]
    with pytest.raises(PartialCopyError) as exc:
        asyncio.run(copy_messages_to_chat(client, 42, msgs))
    assert exc.value.sent == 1
    assert len(client.sent) == 1
