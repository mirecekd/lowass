# tests/test_deps.py
import sys

from lowass import deps


def test_everything_the_app_needs_is_installed_in_this_environment():
    # pyaudiowpatch is Windows only: audio=False
    assert deps.missing("transcribe", audio=False) == []


def test_missing_packages_are_found_and_named_by_their_pip_name(monkeypatch):
    monkeypatch.setitem(sys.modules, "amazon_transcribe", None)  # an import of it now fails
    monkeypatch.setattr(deps.importlib.util, "find_spec", lambda name: None if name == "amazon_transcribe" else object())
    assert deps.missing("transcribe", audio=False) == ["amazon-transcribe"]
    assert deps.missing("groq", audio=False) == []  # the Groq provider does not need it


def test_audio_package_is_only_required_when_audio_is_on(monkeypatch):
    monkeypatch.setattr(deps.importlib.util, "find_spec", lambda name: None if name == "pyaudiowpatch" else object())
    assert deps.missing("transcribe", audio=True) == ["pyaudiowpatch"]
    assert deps.missing("transcribe", audio=False) == []


def test_install_hint_lists_packages_and_the_command():
    text = deps.install_hint(["amazon-transcribe", "mss"])
    assert "amazon-transcribe, mss" in text and "pip install -r requirements.txt" in text


def test_describe_a_missing_module_names_the_package():
    try:
        import amazon_transcribe_not_there  # type: ignore[import-not-found]  # noqa: F401
    except ModuleNotFoundError as exc:
        assert "Missing package 'amazon_transcribe_not_there'" in deps.describe(exc)
    exc2 = ModuleNotFoundError("x", name="amazon_transcribe.client")
    assert "Missing package 'amazon-transcribe'" in deps.describe(exc2) and "pip install" in deps.describe(exc2)
    assert deps.describe(ValueError("boom")) == "ValueError: boom"
