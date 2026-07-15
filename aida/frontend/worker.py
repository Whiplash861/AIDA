from __future__ import annotations

from typing import Callable, List

from PySide6.QtCore import QObject, Signal, Slot

from aida.brain.llm_client import AIDABrain


class BrainWorker(QObject):
    """
    Runs AIDA's language-model request outside the main UI thread.
    """

    response_ready = Signal(str)
    error = Signal(str)
    finished = Signal()

    def __init__(
        self,
        brain: AIDABrain,
        prompt: str,
        context: List[str],
    ) -> None:
        super().__init__()

        self.brain = brain
        self.prompt = prompt
        self.context = context

    @Slot()
    def run(self) -> None:
        try:
            response = self.brain.think(
                user_input=self.prompt,
                context=self.context,
            )

            self.response_ready.emit(response)

        except Exception as exc:
            self.error.emit(str(exc))

        finally:
            self.finished.emit()


class SpeechWorker(QObject):
    """
    Runs AIDA's existing speech pipeline outside the main UI thread.
    """

    error = Signal(str)
    finished = Signal()

    def __init__(
        self,
        speaker: Callable[[str], None],
        text: str,
    ) -> None:
        super().__init__()

        self.speaker = speaker
        self.text = text

    @Slot()
    def run(self) -> None:
        try:
            self.speaker(self.text)

        except Exception as exc:
            self.error.emit(str(exc))

        finally:
            self.finished.emit()