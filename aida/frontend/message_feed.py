from __future__ import annotations

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QTimer,
    Qt,
    Signal,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from aida.frontend.models import (
    ChatMessage,
    MessageSender,
)


class MessageCard(QFrame):
    """
    Full-width glass message surface for one conversation entry.
    """

    def __init__(
        self,
        message: ChatMessage,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        sender_key = {
            MessageSender.USER: "user",
            MessageSender.AIDA: "aida",
            MessageSender.SYSTEM: "system",
        }[message.sender]

        sender_name = {
            MessageSender.USER: "YOU",
            MessageSender.AIDA: "AIDA",
            MessageSender.SYSTEM: "SYSTEM",
        }[message.sender]

        self.setObjectName("messageCard")
        self.setProperty("sender", sender_key)

        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )

        sender_label = QLabel(sender_name)
        sender_label.setObjectName("messageSender")

        timestamp_label = QLabel(
            message.timestamp.strftime("%H:%M:%S")
        )
        timestamp_label.setObjectName("messageTimestamp")

        message_body = QLabel(message.text)
        message_body.setObjectName("messageBody")
        message_body.setTextFormat(
            Qt.TextFormat.PlainText
        )
        message_body.setWordWrap(True)
        message_body.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        message_body.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)
        header_layout.addWidget(sender_label)
        header_layout.addWidget(timestamp_label)
        header_layout.addStretch()

        card_layout = QVBoxLayout()
        card_layout.setContentsMargins(
            14,
            11,
            14,
            13,
        )
        card_layout.setSpacing(6)
        card_layout.addLayout(header_layout)
        card_layout.addWidget(message_body)

        self.setLayout(card_layout)


class AnimatedMessage(QWidget):
    """
    Reveals a message with a restrained fade-and-rise motion.
    """

    reveal_finished = Signal()

    def __init__(
        self,
        card: MessageCard,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self._reveal_offset = 10.0
        self._animation_group: (
            QParallelAnimationGroup | None
        ) = None

        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )

        self._layout = QVBoxLayout()
        self._layout.setSpacing(0)
        self._layout.addWidget(card)

        self.setLayout(self._layout)
        self._set_reveal_offset(10.0)

        self._opacity_effect = (
            QGraphicsOpacityEffect(self)
        )
        self._opacity_effect.setOpacity(0.0)

        self.setGraphicsEffect(
            self._opacity_effect
        )

    def _get_reveal_offset(self) -> float:
        return self._reveal_offset

    def _set_reveal_offset(
        self,
        value: float,
    ) -> None:
        self._reveal_offset = value

        self._layout.setContentsMargins(
            0,
            int(round(value)),
            0,
            0,
        )

        self.updateGeometry()

    revealOffset = Property(
        float,
        _get_reveal_offset,
        _set_reveal_offset,
    )

    def start_reveal(self) -> None:
        if self._animation_group is not None:
            self._animation_group.stop()

        animation_group = QParallelAnimationGroup(
            self
        )

        opacity_animation = QPropertyAnimation(
            self._opacity_effect,
            b"opacity",
            animation_group,
        )
        opacity_animation.setDuration(145)
        opacity_animation.setStartValue(0.0)
        opacity_animation.setEndValue(1.0)
        opacity_animation.setEasingCurve(
            QEasingCurve.Type.OutCubic
        )

        slide_animation = QPropertyAnimation(
            self,
            b"revealOffset",
            animation_group,
        )
        slide_animation.setDuration(165)
        slide_animation.setStartValue(10.0)
        slide_animation.setEndValue(0.0)
        slide_animation.setEasingCurve(
            QEasingCurve.Type.OutCubic
        )

        animation_group.addAnimation(
            opacity_animation
        )
        animation_group.addAnimation(
            slide_animation
        )

        animation_group.finished.connect(
            self._finish_reveal
        )

        self._animation_group = animation_group
        animation_group.start()

    def _finish_reveal(self) -> None:
        self._set_reveal_offset(0.0)
        self._opacity_effect.setOpacity(1.0)
        self.reveal_finished.emit()


class MessageFeed(QScrollArea):
    """
    Scrollable conversation feed containing animated message cards.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.setObjectName("messageFeed")
        self.setWidgetResizable(True)

        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )

        self.viewport().setObjectName(
            "messageFeedViewport"
        )

        self._content = QWidget()
        self._content.setObjectName(
            "messageFeedContent"
        )

        self._feed_layout = QVBoxLayout()
        self._feed_layout.setContentsMargins(
            14,
            14,
            14,
            14,
        )
        self._feed_layout.setSpacing(10)
        self._feed_layout.addStretch()

        self._content.setLayout(
            self._feed_layout
        )

        self.setWidget(self._content)

    def add_message(
        self,
        message: ChatMessage,
        animate: bool = True,
    ) -> None:
        scroll_bar = self.verticalScrollBar()

        distance_from_bottom = (
            scroll_bar.maximum()
            - scroll_bar.value()
        )

        should_follow = (
            distance_from_bottom <= 70
        )

        card = MessageCard(message)
        reveal = AnimatedMessage(card)

        insertion_index = max(
            0,
            self._feed_layout.count() - 1,
        )

        self._feed_layout.insertWidget(
            insertion_index,
            reveal,
        )

        if should_follow:
            reveal.reveal_finished.connect(
                self.scroll_to_bottom
            )

        if animate:
            QTimer.singleShot(
                0,
                lambda: self._begin_reveal(
                    reveal,
                    should_follow,
                ),
            )

        else:
            reveal._finish_reveal()

            if should_follow:
                QTimer.singleShot(
                    0,
                    self.scroll_to_bottom,
                )

    def _begin_reveal(
        self,
        reveal: AnimatedMessage,
        should_follow: bool,
    ) -> None:
        reveal.start_reveal()

        if not should_follow:
            return

        QTimer.singleShot(
            0,
            self.scroll_to_bottom,
        )
        QTimer.singleShot(
            80,
            self.scroll_to_bottom,
        )
        QTimer.singleShot(
            175,
            self.scroll_to_bottom,
        )

    def scroll_to_bottom(self) -> None:
        scroll_bar = self.verticalScrollBar()

        scroll_bar.setValue(
            scroll_bar.maximum()
        )