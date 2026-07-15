from __future__ import annotations

import sys
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from aida.frontend.task_manager import TaskManager


def simulated_task() -> str:
    time.sleep(1)
    return "Task completed successfully."


def main() -> int:
    app = QApplication(sys.argv)
    tasks = TaskManager()

    def handle_result(result: object) -> None:
        print(result)

    def handle_finished() -> None:
        print("Task Manager returned control.")
        QTimer.singleShot(100, app.quit)

    started = tasks.run_task(
        name="test",
        function=simulated_task,
        on_result=handle_result,
        on_error=print,
        on_finished=handle_finished,
    )

    print(f"Task started: {started}")

    exit_code = app.exec()
    tasks.wait_for_done()

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())