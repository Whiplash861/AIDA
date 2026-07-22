from __future__ import annotations

import ast
from pathlib import Path


APP_PATH = Path("aida/frontend/app.py")


def _function(tree: ast.AST, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Function {name!r} was not found")


def _contains_connect_call(function: ast.FunctionDef) -> bool:
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "connect"
        for node in ast.walk(function)
    )


def test_frontend_callbacks_do_not_connect_themselves() -> None:
    source = APP_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)

    restore_callback = _function(tree, "restore_main_window")
    message_callback = _function(tree, "handle_message_displayed")

    assert not _contains_connect_call(restore_callback)
    assert not _contains_connect_call(message_callback)

    assert source.count("overlay.clicked.connect(") == 1
    assert source.count("window.message_displayed.connect(") == 1
    assert source.count("overlay.clicked.disconnect(") == 1
    assert source.count("window.message_displayed.disconnect(") == 1
