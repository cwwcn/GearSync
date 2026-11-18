from dataclasses import dataclass


class SyncError(Exception):
    pass


class Rejected(SyncError):
    pass


@dataclass(frozen=True)
class Activity:
    id: str
    start_ms: int
    sport: str = ''


@dataclass(frozen=True)
class Receipt:
    task_id: str = ''
    remote_id: str = ''


@dataclass(frozen=True)
class ObjectUpload:
    key: str
    bucket: str
    service: str
    md5: str
    size: int


def remote_id(value):
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        text = str(value)
        if 0 < len(text) <= 100 and text.isascii() and all(
            character.isalnum() or character in '_-' for character in text
        ):
            return text
    return ''
