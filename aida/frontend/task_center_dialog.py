from __future__ import annotations

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from aida.assistance.models import AssistanceTaskRecord
from aida.assistance.store import AssistanceTaskStore


class TaskCenterDialog(QDialog):
    """Human-readable history and control surface for durable assistance tasks."""

    refresh_requested = Signal()

    def __init__(
        self,
        store: AssistanceTaskStore,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.store = store
        self._records: dict[str, AssistanceTaskRecord] = {}
        self.setWindowTitle("AIDA Task Center")
        self.resize(900, 560)

        self.list_widget = QListWidget()
        self.list_widget.setMinimumWidth(320)
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)

        self.refresh_button = QPushButton("Refresh")
        self.cancel_button = QPushButton("Request Cancel")
        self.close_button = QPushButton("Close")
        self.status_label = QLabel(
            "Background assistance tasks are local, user-scoped, and independently recorded."
        )
        self.status_label.setWordWrap(True)

        left = QVBoxLayout()
        left.addWidget(QLabel("Recent Tasks"))
        left.addWidget(self.list_widget, stretch=1)

        buttons = QHBoxLayout()
        buttons.addWidget(self.refresh_button)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch()
        buttons.addWidget(self.close_button)

        body = QHBoxLayout()
        body.addLayout(left)
        body.addWidget(self.detail, stretch=1)

        layout = QVBoxLayout(self)
        layout.addWidget(self.status_label)
        layout.addLayout(body, stretch=1)
        layout.addLayout(buttons)

        self.list_widget.currentItemChanged.connect(self._selection_changed)
        self.refresh_button.clicked.connect(self.refresh)
        self.cancel_button.clicked.connect(self._request_cancel)
        self.close_button.clicked.connect(self.close)
        self.refresh()

    @Slot()
    def refresh(self) -> None:
        selected_id = self._selected_task_id()
        self.list_widget.clear()
        self._records = {
            item.task_id: item for item in self.store.list_recent(limit=200)
        }
        selected_item: QListWidgetItem | None = None
        for record in self._records.values():
            item = QListWidgetItem(
                f"{record.title}\n{record.state.value.replace('_', ' ').title()} · {record.updated_at.astimezone().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            item.setData(Qt.ItemDataRole.UserRole, record.task_id)
            self.list_widget.addItem(item)
            if record.task_id == selected_id:
                selected_item = item
        if selected_item is not None:
            self.list_widget.setCurrentItem(selected_item)
        elif self.list_widget.count():
            self.list_widget.setCurrentRow(0)
        else:
            self.detail.setPlainText("No assistance tasks have been recorded.")
            self.cancel_button.setEnabled(False)
        self.refresh_requested.emit()

    @Slot()
    def _request_cancel(self) -> None:
        task_id = self._selected_task_id()
        if not task_id:
            return
        record = self._records.get(task_id)
        if record is None or record.state.terminal:
            QMessageBox.information(
                self,
                "Task already finished",
                "This task is already in a terminal state.",
            )
            return
        self.store.request_cancel(task_id)
        self.refresh()

    @Slot(object, object)
    def _selection_changed(self, current: object, previous: object) -> None:
        del previous
        if not isinstance(current, QListWidgetItem):
            self.detail.clear()
            self.cancel_button.setEnabled(False)
            return
        task_id = str(current.data(Qt.ItemDataRole.UserRole) or "")
        record = self._records.get(task_id)
        if record is None:
            self.detail.clear()
            self.cancel_button.setEnabled(False)
            return
        self.detail.setPlainText(_render_task(record))
        self.cancel_button.setEnabled(not record.state.terminal)

    def _selected_task_id(self) -> str:
        item = self.list_widget.currentItem()
        if item is None:
            return ""
        return str(item.data(Qt.ItemDataRole.UserRole) or "")


def _render_task(record: AssistanceTaskRecord) -> str:
    lines = [
        record.title,
        "=" * len(record.title),
        "",
        f"Task ID: {record.task_id}",
        f"Kind: {record.kind.value.replace('_', ' ').title()}",
        f"State: {record.state.value.replace('_', ' ').title()}",
        f"Risk: {record.risk.value.title()}",
        f"Target: {record.target or 'Not applicable'}",
        f"Authorization required: {'yes' if record.authorization_required else 'no'}",
        f"Authorization ID: {record.authorization_id or 'none'}",
        f"Reversible: {'unknown' if record.reversible is None else 'yes' if record.reversible else 'no'}",
        f"Created: {record.created_at.astimezone().isoformat()}",
        f"Updated: {record.updated_at.astimezone().isoformat()}",
    ]
    if record.progress_detail:
        lines.extend(["", "Progress", "--------", record.progress_detail])
    if record.result_summary:
        lines.extend(["", "Result", "------", record.result_summary])
    if record.error_detail:
        lines.extend(["", "Error", "-----", record.error_detail])
    if record.metadata:
        lines.extend(["", "Recorded context", "----------------"])
        for key, value in sorted(record.metadata.items()):
            lines.append(f"{key}: {value}")
    return "\n".join(lines)
