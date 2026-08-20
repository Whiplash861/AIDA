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
    include_in_context: bool = True


MessageListener = Callable[[ChatMessage], None]


class ChatHistory:
    """
    Stores the messages in the active AIDA conversation and
    notifies listeners whenever a message is added.
    """

    def __init__(
        self,
        message_saver: Optional[
            Callable[[ChatMessage], None]
        ] = None,
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
        include_in_context: bool = True,
    ) -> ChatMessage:
        clean_text = text.strip()

        if not clean_text:
            raise ValueError("Message text cannot be empty")

        message = ChatMessage(
            sender=sender,
            text=clean_text,
            include_in_context=include_in_context,
        )

        self._messages.append(message)

        if self._message_saver is not None:
            self._message_saver(message)

        self._notify_listeners(message)

        return message

    def add_user(
        self,
        text: str,
        *,
        include_in_context: bool = True,
    ) -> ChatMessage:
        return self.add(
            MessageSender.USER,
            text,
            include_in_context=include_in_context,
        )

    def add_aida(
        self,
        text: str,
        *,
        include_in_context: bool = True,
    ) -> ChatMessage:
        return self.add(
            MessageSender.AIDA,
            text,
            include_in_context=include_in_context,
        )

    def add_system(
        self,
        text: str,
        *,
        include_in_context: bool = True,
    ) -> ChatMessage:
        return self.add(
            MessageSender.SYSTEM,
            text,
            include_in_context=include_in_context,
        )

    def mark_latest_local_only(self) -> None:
        """
        Excludes the newest user message from future language-model
        context while keeping it visible and stored locally.
        """

        for message in reversed(self._messages):
            if message.sender is MessageSender.USER:
                message.include_in_context = False
                return

    def subscribe(self, listener: MessageListener) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def unsubscribe(self, listener: MessageListener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def _notify_listeners(self, message: ChatMessage) -> None:
        for listener in self._listeners.copy():
            listener(message)

    def clear(self) -> None:
        self._messages.clear()

    def recent_context(self, limit: int = 12) -> List[str]:
        if limit <= 0:
            return []

        eligible_messages = [
            message
            for message in self._messages
            if message.include_in_context
        ][-limit:]

        context: List[str] = []

        for message in eligible_messages:
            sender_name = {
                MessageSender.USER: "User",
                MessageSender.AIDA: "AIDA",
                MessageSender.SYSTEM: "System",
            }[message.sender]

            context.append(
                f"{sender_name}: {message.text}"
            )

        return context
