from __future__ import annotations

from dotenv import load_dotenv

from aida.config import get_config
from aida.frontend.command_router import CommandType
from aida.frontend.commands.registry import CommandRegistry


def main() -> None:
    load_dotenv()

    config = get_config()
    registry = CommandRegistry(config)

    executor = registry.get(
        CommandType.QUICKSCAN
    )

    if executor is None:
        raise RuntimeError(
            "Quickscan executor was not registered."
        )

    print(f"Task name: {executor.task_name}")
    print(f"Start message: {executor.start_message}")
    print()

    result = executor.execute()

    print(result.transcript_text)
    print()
    print(f"Speech summary: {result.speech_text}")


if __name__ == "__main__":
    main()