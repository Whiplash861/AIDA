
from __future__ import annotations

from enum import StrEnum

from aida.frontend.commands.base import (
    CommandCategory,
    CommandExecutor,
    CommandResult,
)
from aida.memory.renderer import render_memory
from aida.memory.service import MemoryService


class MemoryOperation(StrEnum):
    SHOW = "show"
    SEARCH = "search"
    ADD = "add"
    DELETE = "delete"
    REVISE = "revise"


class MemoryCommandExecutor(CommandExecutor):
    def __init__(
        self,
        service: MemoryService,
        operation: MemoryOperation,
        *,
        slots: dict[str, object] | None = None,
    ) -> None:
        self.service = service
        self.operation = operation
        self.slots = slots or {}

    @property
    def task_name(self) -> str:
        return f"memory_{self.operation.value}"

    @property
    def category(self) -> CommandCategory:
        return CommandCategory.MEMORY

    @property
    def start_message(self) -> str:
        return {
            MemoryOperation.SHOW: "Opening recent operational memories.",
            MemoryOperation.SEARCH: "Searching AIDA's local Memory Bank.",
            MemoryOperation.ADD: "Preparing a user-created memory.",
            MemoryOperation.DELETE: "Removing the selected memory from active use.",
            MemoryOperation.REVISE: "Revising the selected memory.",
        }[self.operation]

    def execute(self) -> CommandResult:
        if self.operation is MemoryOperation.SHOW:
            items = self.service.list_memories(limit=20)
            return _list_result(items, "Recent AIDA memories")

        if self.operation is MemoryOperation.SEARCH:
            query = str(self.slots.get("query") or "").strip()
            if not query:
                return CommandResult(
                    transcript_text=(
                        "Memory search was not started.\n\n"
                        "State what AIDA should look for. "
                        "Example: Search memory for Outlook startup failures."
                    ),
                    speech_text="State what you want me to search for.",
                )
            return _list_result(
                self.service.search(query, limit=30),
                f"Memory results for: {query}",
            )

        if self.operation is MemoryOperation.ADD:
            text = str(self.slots.get("memory_text") or "").strip()
            if not text:
                return CommandResult(
                    transcript_text=(
                        "No memory was added. State the information AIDA should remember."
                    ),
                    speech_text="State what you want me to remember.",
                )
            item = self.service.add_memory(
                category="user.note",
                title="User-created memory",
                summary=text,
                facts={"entered_by_user": True},
                confidence=1.0,
                confidence_basis=("The user directly supplied this memory.",),
                tags=("user-created",),
                source=self.service.user_id,
            )
            return CommandResult(
                transcript_text=(
                    "Memory added.\n\n"
                    f"Memory ID: {item.memory_id}\n"
                    f"{item.summary}"
                ),
                speech_text="The memory was added to your local Memory Bank.",
            )

        memory_id = str(self.slots.get("memory_id") or "").strip()
        if not memory_id:
            return CommandResult(
                transcript_text=(
                    "The memory could not be changed because no exact Memory ID was provided."
                ),
                speech_text="Provide the exact Memory ID.",
            )

        if self.operation is MemoryOperation.DELETE:
            self.service.soft_delete(
                memory_id,
                reason="Direct user request from the frontend",
            )
            return CommandResult(
                transcript_text=(
                    f"Memory {memory_id} was removed from active memory. "
                    "Its deletion record remains so stale events do not recreate it automatically."
                ),
                speech_text="The selected memory was removed from active memory.",
            )

        revision = str(self.slots.get("revision_text") or "").strip()
        if not revision:
            return CommandResult(
                transcript_text=(
                    "The memory was not revised. Provide the corrected plain-language summary "
                    "after a colon."
                ),
                speech_text="Provide the corrected memory summary.",
            )
        item = self.service.revise_memory(
            memory_id,
            summary=revision,
            reason="Direct user correction",
            revised_by=self.service.user_id,
        )
        return CommandResult(
            transcript_text=(
                "Memory revised.\n\n"
                f"Memory ID: {item.memory_id}\n"
                f"Current summary: {item.summary}"
            ),
            speech_text="The selected memory was revised.",
        )


def _list_result(items: list[object], heading: str) -> CommandResult:
    if not items:
        return CommandResult(
            transcript_text=f"{heading}\n\nNo matching memories were found.",
            speech_text="No matching memories were found.",
        )
    rendered = []
    for item in items:
        rendered.append(render_memory(item))
    return CommandResult(
        transcript_text=heading + "\n\n" + "\n\n---\n\n".join(rendered),
        speech_text=f"{len(items)} matching memories are available in the transcript.",
    )
