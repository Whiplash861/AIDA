from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Callable, List, Optional


class MessageSender(Enum):
    USER = auto()
    AIDA = auto()
    SYSTEM = auto()


@dataclass(slots=True)
class ChatMessage:
    sender: MessageSender
    text: str
    timestamp: datetime = field(default_factory=datetime.now)
    source_component: str | None = None
    message_kind: str | None = None


MessageListener = Callable[[ChatMessage], None]


class ChatHistory:
    def __init__(
        self,
        message_saver: Optional[Callable[[ChatMessage], None]] = None,
    ) -> None:
        self._messages: List[ChatMessage] = []
        self._listeners: List[MessageListener] = []
        self._message_saver = message_saver

    @property
    def messages(self) -> tuple[ChatMessage, ...]:
        return tuple(self._messages)

    def add(
        self,
        sender: MessageSender,
        text: str,
        *,
        source_component: str | None = None,
        message_kind: str | None = None,
    ) -> ChatMessage:
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("Message text cannot be empty")
        message = ChatMessage(
            sender=sender,
            text=clean_text,
            source_component=source_component,
            message_kind=message_kind,
        )
        self._messages.append(message)
        if self._message_saver is not None:
            self._message_saver(message)
        for listener in self._listeners.copy():
            listener(message)
        return message

    def add_user(self, text: str) -> ChatMessage:
        return self.add(MessageSender.USER, text)

    def add_aida(self, text: str) -> ChatMessage:
        return self.add(MessageSender.AIDA, text)

    def add_system(
        self,
        text: str,
        *,
        source_component: str | None = None,
        message_kind: str | None = None,
    ) -> ChatMessage:
        return self.add(
            MessageSender.SYSTEM,
            text,
            source_component=source_component,
            message_kind=message_kind,
        )

    def subscribe(self, listener: MessageListener) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def unsubscribe(self, listener: MessageListener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def clear(self) -> None:
        self._messages.clear()

    def recent_context(self, limit: int = 12) -> List[str]:
        if limit <= 0:
            return []
        labels = {
            MessageSender.USER: "User",
            MessageSender.AIDA: "AIDA",
            MessageSender.SYSTEM: "System",
        }
        return [
            f"{labels[message.sender]}: {message.text}"
            for message in self._messages[-limit:]
        ]
