
import pytest
from aida.intent.defaults import build_default_intent_registry
from aida.intent.resolver import IntentResolver

@pytest.fixture
def resolver():
    return IntentResolver(build_default_intent_registry())

@pytest.mark.parametrize("phrase", [
    "perform a surface-level scan",
    "start a surface scan",
    "initiate low-level scan",
    "run a basic malware scan",
    "quick malware scan",
])
def test_surface_paraphrases(resolver, phrase):
    result=resolver.resolve(phrase)
    assert result.resolved is not None
    assert result.resolved.intent_id=="security.scan.surface"

def test_full_and_deep(resolver):
    assert resolver.resolve("perform a full system sweep").resolved.intent_id=="security.scan.full"
    deep=resolver.resolve(r'deep scan "C:\Users\Austin\Downloads"').resolved
    assert deep.intent_id=="security.scan.deep"
    assert deep.slots["target_path"]==r"C:\Users\Austin\Downloads"

def test_diagnostic_quickscan_keeps_legacy_meaning(resolver):
    result=resolver.resolve("quick scan")
    assert result.resolved.intent_id=="diagnostics.quickscan"

def test_memory_and_application_slots(resolver):
    add=resolver.resolve("remember that browser passwords must never be cleared").resolved
    assert add.intent_id=="memory.add"
    assert "browser passwords" in add.slots["memory_text"]
    app=resolver.resolve("diagnose outlook").resolved
    assert app.slots["application_name"]=="outlook"

def test_confirmation_phrase_is_exact_intent(resolver):
    assert resolver.resolve("confirm scan cancellation").resolved.intent_id=="security.scan.cancel.confirm"
    # A generic yes must not authorize anything.
    assert resolver.resolve("yes").resolved is None


@pytest.mark.parametrize(
    ("phrase","intent_id","application"),
    [
        ("repair outlook","application.repair.plan","outlook"),
        ("clear chrome cache","application.cache.plan","chrome"),
        ("restart edge","application.restart.plan","edge"),
    ],
)
def test_application_recovery_intents(resolver, phrase, intent_id, application):
    result=resolver.resolve(phrase).resolved
    assert result.intent_id==intent_id
    assert result.slots["application_name"]==application
