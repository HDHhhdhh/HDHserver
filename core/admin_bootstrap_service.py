"""Canonical first-render snapshot; the caller owns authentication and leases."""
from __future__ import annotations

from core.date_rules import parse_iso_date_key
from core.json_revision import json_revision

PAYLOAD_KEYS = ('students', 'videos', 'updates', 'logs', 'absent', 'progress', 'schoolCal')


class AdminBootstrapService:
    def __init__(self, readers, *, optional_error=None):
        self._readers = dict(readers)
        if set(self._readers) != set(PAYLOAD_KEYS) or any(not callable(reader) for reader in self._readers.values()):
            raise TypeError('seven canonical bootstrap readers are required')
        self._optional_error = optional_error

    def load(self, date):
        parsed = parse_iso_date_key(date)
        if parsed is None:
            raise ValueError('invalid admin bootstrap date')
        date = parsed.isoformat()
        payload = {}
        for key in PAYLOAD_KEYS:
            try:
                payload[key] = self._readers[key](date)
            except Exception as error:
                if key not in {'absent', 'schoolCal'}:
                    raise
                if self._optional_error is not None:
                    self._optional_error(key, error)
                payload[key] = {}
        for key in ('students', 'videos'):
            if not isinstance(payload[key], list) or any(not isinstance(row, dict) for row in payload[key]):
                raise ValueError('invalid bootstrap array: ' + key)
        for key in ('updates', 'logs', 'progress'):
            if not isinstance(payload[key], dict):
                raise ValueError('invalid critical bootstrap map: ' + key)
        return {'date': date, **payload,
                'revisions': {key: json_revision(payload[key]) for key in PAYLOAD_KEYS}}
