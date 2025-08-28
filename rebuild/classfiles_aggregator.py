from __future__ import annotations

from typing import Dict, Any
import hashlib

from shared.constants import HOST_CLASS_ID, LOCAL_CLASS_ID


_host_blob = bytearray()
_local_blob = bytearray()
_host_index: Dict[bytes, int] = {}
_local_index: Dict[bytes, int] = {}


def reset() -> None:
    _host_blob.clear()
    _local_blob.clear()
    _host_index.clear()
    _local_index.clear()


def register_host(data: bytes | bytearray) -> int:
    # Relâcher la dédup: toujours appendre (comportement proche de l'original)
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("register_host attend bytes ou bytearray")
    offset = len(_host_blob)
    _host_blob.extend(data)
    return offset


def register_local(data: bytes | bytearray) -> int:
    # Déduplication par empreinte SHA-1 (comme l'original)
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("register_local attend bytes ou bytearray")
    digest = hashlib.sha1(bytes(data)).digest()
    if digest in _local_index:
        return _local_index[digest]
    offset = len(_local_blob)
    _local_blob.extend(data)
    _local_index[digest] = offset
    return offset


def build_sections() -> Dict[int, Dict[str, Any]]:
    sections: Dict[int, Dict[str, Any]] = {}
    if len(_host_blob) > 0:
        sections[HOST_CLASS_ID] = {
            'flag': 0x00,
            'count': 1,
            'size': len(_host_blob),
            'data': bytes(_host_blob),
        }
    if len(_local_blob) > 0:
        sections[LOCAL_CLASS_ID] = {
            'flag': 0x00,
            'count': 1,
            'size': len(_local_blob),
            'data': bytes(_local_blob),
        }
    return sections


