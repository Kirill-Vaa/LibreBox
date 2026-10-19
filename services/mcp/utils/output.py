import codecs
from collections import deque
from typing import Final


_TAIL_PIECE_MERGE_CHARS: Final[int] = 512


def _truncation_marker(omitted_chars: int) -> str:
    return f"\n[... {omitted_chars} chars truncated ...]\n"


class OutputCapture:
    def __init__(self, char_limit: int) -> None:
        self._head_limit = char_limit // 2
        self._tail_limit = char_limit - self._head_limit
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._head = ""
        self._tail_pieces: deque[str] = deque()
        self._tail_length = 0
        self._omitted_chars = 0

    def append(self, data: bytes) -> None:
        self._absorb(self._decoder.decode(data))

    def render(self) -> tuple[str, bool]:
        self._absorb(self._decoder.decode(b"", True))
        tail = "".join(self._tail_pieces)
        if not self._omitted_chars:
            return f"{self._head}{tail}", False

        return f"{self._head}{_truncation_marker(self._omitted_chars)}{tail}", True

    def _absorb(self, text: str) -> None:
        head_room = self._head_limit - len(self._head)
        if head_room > 0:
            self._head += text[:head_room]
            text = text[head_room:]

        if not text:
            return

        if len(text) >= self._tail_limit:
            self._omitted_chars += self._tail_length + len(text) - self._tail_limit
            self._tail_pieces.clear()
            kept_text = text[len(text) - self._tail_limit :] if self._tail_limit else ""
            if kept_text:
                self._tail_pieces.append(kept_text)

            self._tail_length = len(kept_text)
            return

        if self._tail_pieces and len(self._tail_pieces[-1]) < _TAIL_PIECE_MERGE_CHARS:
            self._tail_pieces[-1] += text
        else:
            self._tail_pieces.append(text)

        self._tail_length += len(text)
        self._drop_overflow()

    def _drop_overflow(self) -> None:
        overflow = self._tail_length - self._tail_limit
        while overflow > 0:
            oldest_piece = self._tail_pieces[0]
            if len(oldest_piece) <= overflow:
                self._tail_pieces.popleft()
                overflow -= len(oldest_piece)
                self._tail_length -= len(oldest_piece)
                self._omitted_chars += len(oldest_piece)
                continue

            self._tail_pieces[0] = oldest_piece[overflow:]
            self._tail_length -= overflow
            self._omitted_chars += overflow
            overflow = 0
