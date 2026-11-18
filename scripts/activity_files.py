import hashlib
import io
import logging
import os
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

import crcmod

from sync_types import SyncError


MAX_BYTES = 64 * 1024 * 1024
fit_crc = crcmod.mkCrcFun(0x18005, initCrc=0, rev=True, xorOut=0)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ActivityFile:
    original: bytes
    fit: bytes
    archive: bool = False

    @property
    def digest(self):
        return hashlib.sha256(self.fit).hexdigest()

    @property
    def original_digest(self):
        return hashlib.sha256(self.original).hexdigest()

    def coros_archive(self, activity_id):
        if self.archive:
            return self.original
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr(zipfile.ZipInfo(f'{activity_id}.fit'), self.fit, compress_type=zipfile.ZIP_DEFLATED)
        return output.getvalue()


def checked_fit(data):
    if len(data) < 14 or data[0] not in (12, 14) or data[8:12] != b'.FIT':
        raise SyncError('Invalid FIT header')
    header_size = data[0]
    data_size = int.from_bytes(data[4:8], 'little')
    if not data_size or len(data) != header_size + data_size + 2:
        raise SyncError('Invalid FIT data length')
    if header_size == 14:
        header_crc = int.from_bytes(data[12:14], 'little')
        if header_crc and fit_crc(data[:12]) != header_crc:
            raise SyncError('Invalid FIT header checksum')
    if fit_crc(data[:-2]) != int.from_bytes(data[-2:], 'little'):
        raise SyncError('Invalid FIT file checksum')
    return data


def decode_activity(data):
    if not isinstance(data, bytes) or not data or len(data) > MAX_BYTES:
        raise SyncError('Activity file is empty or exceeds the size limit')
    if not data.startswith(b'PK'):
        return ActivityFile(data, checked_fit(data))
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            if len(members) > 64 or sum(member.file_size for member in members) > MAX_BYTES:
                raise SyncError('Activity archive exceeds limits')
            if any(
                member.filename.startswith(('/', '\\')) or '\\' in member.filename
                or '..' in member.filename.split('/') or ':' in member.filename
                or stat.S_ISLNK(member.external_attr >> 16)
                for member in members
            ):
                raise SyncError('Activity archive contains unsafe member names or types')
            candidates = [member for member in members if not member.is_dir() and member.filename.lower().endswith('.fit')]
            if len(candidates) != 1:
                raise SyncError('Activity archive must have exactly one FIT file')
            fit = checked_fit(archive.read(candidates[0]))
            return ActivityFile(data, fit, True)
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError, EOFError) as error:
        raise SyncError('Invalid activity ZIP or checksum') from error


class ActivityCache:
    def __init__(self, directory):
        self.directory = Path(directory)

    def path(self, activity, suffix):
        return self.directory / f'{activity.id}.{suffix}'

    def read(self, activity):
        try:
            with self.path(activity, 'original').open('rb') as stream:
                return decode_activity(stream.read(MAX_BYTES + 1))
        except FileNotFoundError:
            return None

    def write(self, activity, suffix, data):
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=self.directory, delete=False) as stream:
            temporary = Path(stream.name)
            try:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
                stream.close()
                os.replace(temporary, self.path(activity, suffix))
            finally:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    logger.warning('Could not clean up an activity staging file')
        return self.path(activity, suffix)
