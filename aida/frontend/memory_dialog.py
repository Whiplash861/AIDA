
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from aida.memory.models import JournalEvent, MemoryItem
from aida.memory.renderer import render_event, render_memory
from aida.memory.service import MemoryService


class MemoryBankDialog(QDialog):
    """Human-readable local Memory Bank editor."""

    def __init__(
        self,
        service: MemoryService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self._items_by_id: dict[str, MemoryItem] = {}
        self._selected_memory_id: str | None = None
        self._events_by_id: dict[str, JournalEvent] = {}

        self.setWindowTitle("AIDA Memory Bank")
        self.resize(900, 620)
        self.setMinimumSize(720, 480)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText(
            "Search historical fixes, authorizations, Stand Down items, applications, or findings..."
        )
        self.search_button = QPushButton("Search")
        self.refresh_button = QPushButton("Recent")

        self.memory_list = QListWidget()
        self.memory_list.setMinimumWidth(300)

        self.title_box = QLineEdit()
        self.title_box.setPlaceholderText("Memory title")
        self.category_box = QLineEdit()
        self.category_box.setPlaceholderText(
            "Category, such as security.preference or application.outlook"
        )
        self.summary_box = QTextEdit()
        self.summary_box.setPlaceholderText(
            "Write the memory in plain language. AIDA stores the structured record separately."
        )

        self.detail_label = QLabel(
            "Select a memory to view its current plain-language record."
        )
        self.detail_label.setWordWrap(True)
        self.detail_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        self.event_list = QListWidget()
        self.event_detail = QLabel(
            "Select an event to read its plain-language operational record."
        )
        self.event_detail.setWordWrap(True)
        self.event_detail.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        self.new_button = QPushButton("New")
        self.save_button = QPushButton("Save Revision")
        self.delete_button = QPushButton("Remove")
        self.close_button = QPushButton("Close")

        self._build_layout()
        self._connect()
        self.refresh()

    def _build_layout(self) -> None:
        search_layout = QHBoxLayout()
        search_layout.addWidget(self.search_box, 1)
        search_layout.addWidget(self.search_button)
        search_layout.addWidget(self.refresh_button)

        editor = QWidget()
        editor_layout = QVBoxLayout(editor)
        editor_layout.addWidget(QLabel("Title"))
        editor_layout.addWidget(self.title_box)
        editor_layout.addWidget(QLabel("Category"))
        editor_layout.addWidget(self.category_box)
        editor_layout.addWidget(QLabel("Plain-language memory"))
        editor_layout.addWidget(self.summary_box, 1)
        editor_layout.addWidget(QLabel("Current record"))
        editor_layout.addWidget(self.detail_label)

        action_layout = QHBoxLayout()
        action_layout.addWidget(self.new_button)
        action_layout.addWidget(self.save_button)
        action_layout.addWidget(self.delete_button)
        action_layout.addStretch()
        action_layout.addWidget(self.close_button)
        editor_layout.addLayout(action_layout)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.memory_list)
        splitter.addWidget(editor)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([320, 580])

        timeline = QWidget()
        timeline_layout = QHBoxLayout(timeline)
        timeline_layout.addWidget(self.event_list, 1)
        timeline_layout.addWidget(self.event_detail, 2)

        tabs = QTabWidget()
        tabs.addTab(splitter, "Memories")
        tabs.addTab(timeline, "Event Timeline")

        layout = QVBoxLayout(self)
        layout.addLayout(search_layout)
        layout.addWidget(tabs, 1)

    def _connect(self) -> None:
        self.search_button.clicked.connect(self.search)
        self.refresh_button.clicked.connect(self.refresh)
        self.search_box.returnPressed.connect(self.search)
        self.memory_list.currentItemChanged.connect(
            self._selection_changed
        )
        self.event_list.currentItemChanged.connect(
            self._event_selection_changed
        )
        self.new_button.clicked.connect(self.new_memory)
        self.save_button.clicked.connect(self.save)
        self.delete_button.clicked.connect(self.remove)
        self.close_button.clicked.connect(self.close)

    def refresh(self) -> None:
        self._populate(self.service.list_memories(limit=250))
        self._populate_events(self.service.list_events(limit=500))

    def search(self) -> None:
        query = self.search_box.text().strip()
        self._populate(
            self.service.search(query, limit=250)
            if query
            else self.service.list_memories(limit=250)
        )

    def new_memory(self) -> None:
        self._selected_memory_id = None
        self.memory_list.clearSelection()
        self.title_box.setText("")
        self.category_box.setText("user.note")
        self.summary_box.setPlainText("")
        self.detail_label.setText(
            "New user-created memory. Save it after writing a plain-language summary."
        )
        self.title_box.setFocus()

    def save(self) -> None:
        title = self.title_box.text().strip()
        category = self.category_box.text().strip()
        summary = self.summary_box.toPlainText().strip()
        if not title or not category or not summary:
            QMessageBox.warning(
                self,
                "Memory incomplete",
                "Title, category, and plain-language memory are required.",
            )
            return

        if self._selected_memory_id is None:
            item = self.service.add_memory(
                category=category,
                title=title,
                summary=summary,
                facts={"entered_through_memory_bank": True},
                confidence=1.0,
                confidence_basis=(
                    "The user directly entered this memory.",
                ),
                tags=("user-created",),
                source=self.service.user_id,
            )
            self._selected_memory_id = item.memory_id
        else:
            item = self.service.revise_memory(
                self._selected_memory_id,
                title=title,
                summary=summary,
                reason="User revision in the Memory Bank frontend",
                revised_by=self.service.user_id,
            )

        self.refresh()
        self._select_id(item.memory_id)

    def remove(self) -> None:
        if self._selected_memory_id is None:
            return
        item = self._items_by_id.get(self._selected_memory_id)
        if item is None:
            return
        response = QMessageBox.question(
            self,
            "Remove memory",
            (
                f"Remove '{item.title}' from active memory?\n\n"
                "A deletion marker remains so old events do not immediately recreate it."
            ),
        )
        if response != QMessageBox.StandardButton.Yes:
            return
        self.service.soft_delete(
            item.memory_id,
            reason="User removal through the Memory Bank frontend",
        )
        self.new_memory()
        self.refresh()

    def _populate(self, items: list[MemoryItem]) -> None:
        self.memory_list.clear()
        self._items_by_id = {item.memory_id: item for item in items}
        for item in items:
            confidence = round(item.confidence * 100)
            label = (
                f"{item.title}\n"
                f"{item.category.replace('_', ' ')} · {confidence}% confidence"
            )
            list_item = QListWidgetItem(label)
            list_item.setData(
                Qt.ItemDataRole.UserRole,
                item.memory_id,
            )
            self.memory_list.addItem(list_item)

    def _selection_changed(
        self,
        current: QListWidgetItem | None,
        previous: QListWidgetItem | None,
    ) -> None:
        del previous
        if current is None:
            return
        memory_id = str(
            current.data(Qt.ItemDataRole.UserRole) or ""
        )
        item = self._items_by_id.get(memory_id)
        if item is None:
            return
        self._selected_memory_id = item.memory_id
        self.title_box.setText(item.title)
        self.category_box.setText(item.category)
        self.summary_box.setPlainText(item.summary)
        self.detail_label.setText(render_memory(item))

    def _populate_events(self, events: list[JournalEvent]) -> None:
        self.event_list.clear()
        self._events_by_id = {event.event_id: event for event in events}
        for event in events:
            label = (
                f"{event.created_at.astimezone().strftime('%b %d %I:%M %p')} — "
                f"{event.summary}"
            )
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, event.event_id)
            self.event_list.addItem(item)

    def _event_selection_changed(
        self,
        current: QListWidgetItem | None,
        previous: QListWidgetItem | None,
    ) -> None:
        del previous
        if current is None:
            return
        event_id = str(current.data(Qt.ItemDataRole.UserRole) or "")
        event = self._events_by_id.get(event_id)
        if event is not None:
            self.event_detail.setText(render_event(event))

    def _select_id(self, memory_id: str) -> None:
        for index in range(self.memory_list.count()):
            item = self.memory_list.item(index)
            if str(item.data(Qt.ItemDataRole.UserRole)) == memory_id:
                self.memory_list.setCurrentItem(item)
                return
