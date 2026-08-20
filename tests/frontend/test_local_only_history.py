from aida.frontend.models import ChatHistory


def test_local_only_messages_are_excluded_from_context() -> None:
    history = ChatHistory()
    history.add_user("normal request")
    history.add_user(
        "deep scan C:\\private",
        include_in_context=False,
    )
    history.add_aida(
        "sensitive result",
        include_in_context=False,
    )
    history.add_aida("normal response")

    assert history.recent_context() == [
        "User: normal request",
        "AIDA: normal response",
    ]


def test_mark_latest_local_only_marks_latest_user_message() -> None:
    history = ChatHistory()
    history.add_user("security command")
    history.add_system("starting")
    history.mark_latest_local_only()

    assert history.messages[0].include_in_context is False
    assert history.messages[1].include_in_context is True
