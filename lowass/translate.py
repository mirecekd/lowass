# lowass/translate.py
"""Instant translation of transcribed text through Amazon Translate."""
import logging
import re

import boto3

log = logging.getLogger('lowass.translate')

MAX_CHUNK_BYTES = 9000
_SPECIAL_CODES = {'zh-CN': 'zh', 'zh-TW': 'zh-TW'}
_SENTENCE_END = re.compile(r'(?<=[.!?。！？])\s+')


def _base(lang_code: str) -> str:
    return lang_code.split('-')[0].lower()


def to_translate_code(lang_code: str) -> str:
    """Map an Amazon Transcribe language code to an Amazon Translate one."""
    return _SPECIAL_CODES.get(lang_code, _base(lang_code))


def _hard_split(piece: str, limit: int) -> list[str]:
    """Split a piece that has no sentence boundary into limit-sized parts."""
    parts: list[str] = []
    current = ''
    for char in piece:
        if len((current + char).encode('utf-8')) > limit:
            parts.append(current)
            current = ''
        current += char
    if current:
        parts.append(current)
    return parts


def split_text(text: str, limit: int = MAX_CHUNK_BYTES) -> list[str]:
    """Split text on sentence boundaries into chunks of at most limit bytes."""
    if len(text.encode('utf-8')) <= limit:
        return [text]
    chunks: list[str] = []
    current = ''
    for sentence in _SENTENCE_END.split(text):
        pieces = ([sentence] if len(sentence.encode('utf-8')) <= limit
                  else _hard_split(sentence, limit))
        for piece in pieces:
            candidate = f'{current} {piece}' if current else piece
            if len(candidate.encode('utf-8')) <= limit:
                current = candidate
            else:
                chunks.append(current)
                current = piece
    if current:
        chunks.append(current)
    return chunks


class Translator:
    def __init__(self, profile: str, region: str, target: str = 'cs',
                 understood: tuple[str, ...] = ('cs', 'sk', 'en'), client=None):
        self.profile = profile
        self.region = region
        self.target = target
        self.understood = understood
        self._client = client

    def needed(self, lang_code: str | None) -> bool:
        if not lang_code:
            return False
        base = _base(lang_code)
        return base not in self.understood and base != self.target

    def translate(self, text: str, lang_code: str) -> str | None:
        if not self.needed(lang_code) or not text.strip():
            return None
        try:
            client = self._get_client()
            source = to_translate_code(lang_code)
            parts = []
            for chunk in split_text(text.strip()):
                response = client.translate_text(
                    Text=chunk, SourceLanguageCode=source,
                    TargetLanguageCode=self.target)
                parts.append(response['TranslatedText'])
            return ' '.join(parts)
        except Exception:
            log.exception('translation failed for %s', lang_code)
            return None

    def _get_client(self):
        if self._client is None:
            session = boto3.Session(profile_name=self.profile,
                                    region_name=self.region)
            self._client = session.client('translate')
        return self._client
