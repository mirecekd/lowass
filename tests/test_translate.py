# tests/test_translate.py
import pytest

from lowass.translate import Translator, split_text, to_translate_code


class FakeClient:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def translate_text(self, **kwargs):
        if self.fail:
            raise RuntimeError('boom')
        self.calls.append(kwargs)
        return {'TranslatedText': 'T:' + kwargs['Text']}


def make(client=None):
    return Translator('ai', 'eu-central-1', client=client or FakeClient())


@pytest.mark.parametrize('code, expected', [
    (None, False), ('', False),
    ('cs-CZ', False), ('sk-SK', False), ('en-US', False),
    ('de-DE', True), ('zh-CN', True), ('fr-FR', True),
])
def test_needed(code, expected):
    assert make().needed(code) is expected


def test_needed_false_for_target_language():
    t = Translator('ai', 'eu-central-1', target='de', understood=(),
                   client=FakeClient())
    assert t.needed('de-DE') is False
    assert t.needed('cs-CZ') is True


@pytest.mark.parametrize('code, expected', [
    ('de-DE', 'de'), ('zh-CN', 'zh'), ('zh-TW', 'zh-TW'), ('en-US', 'en'),
])
def test_code_mapping(code, expected):
    assert to_translate_code(code) == expected


def test_fake_receives_source_and_target():
    client = FakeClient()
    result = make(client).translate('Hallo Welt', 'de-DE')
    assert result == 'T:Hallo Welt'
    assert client.calls == [{'Text': 'Hallo Welt', 'SourceLanguageCode': 'de',
                             'TargetLanguageCode': 'cs'}]


def test_chinese_source_code_is_mapped():
    client = FakeClient()
    make(client).translate('你好', 'zh-CN')
    assert client.calls[0]['SourceLanguageCode'] == 'zh'


def test_not_needed_returns_none_without_call():
    client = FakeClient()
    assert make(client).translate('Hello', 'en-US') is None
    assert client.calls == []


def test_blank_text_returns_none():
    client = FakeClient()
    assert make(client).translate('   ', 'de-DE') is None
    assert client.calls == []


def test_failure_returns_none():
    assert make(FakeClient(fail=True)).translate('Hallo', 'de-DE') is None


def test_long_text_is_split_and_joined():
    sentence = 'Das ist ein Satz. '
    text = sentence * 1000
    client = FakeClient()
    result = make(client).translate(text, 'de-DE')
    assert len(client.calls) > 1
    assert all(len(c['Text'].encode()) <= 9000 for c in client.calls)
    assert result is not None
    assert result.count('Das ist ein Satz.') == 1000


def test_split_text_breaks_oversized_sentence():
    chunks = split_text('x' * 25, limit=10)
    assert chunks == ['x' * 10, 'x' * 10, 'x' * 5]
