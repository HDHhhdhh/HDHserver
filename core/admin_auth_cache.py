"""Bounded process-local reuse of successful, configuration-bound checks."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections import OrderedDict
from collections.abc import Callable


class SuccessfulAuthCache:
    def __init__(
        self,
        *,
        ttl_seconds: float = 5.0,
        max_entries: int = 64,
        max_inflight: int = 8,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._max_inflight = max_inflight
        self._clock = clock
        self._secret = secrets.token_bytes(32)
        self._lock = threading.Lock()
        self._configuration: bytes | None = None
        self._generation = 0
        self._successes: OrderedDict[bytes, float] = OrderedDict()
        self._inflight: dict[bytes, threading.Event] = {}

    def _digest(self, domain: bytes, *values: str) -> bytes:
        digest = hmac.new(self._secret, domain, hashlib.sha256)
        for value in values:
            encoded = value.encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
        return digest.digest()

    def observe_configuration(self, username: str, password_hash: str) -> int:
        try:
            configuration = self._digest(b"configuration", username, password_hash) if username and password_hash else None
        except UnicodeEncodeError:
            configuration = None
        with self._lock:
            if configuration != self._configuration:
                self._configuration = configuration
                self._generation += 1
                self._successes.clear()
                for event in self._inflight.values():
                    event.set()
                self._inflight.clear()
            return self._generation

    def verify(
        self,
        generation: int,
        username: str,
        password: str,
        check: Callable[[], bool],
    ) -> bool:
        try:
            key = self._digest(b"credentials", username, password)
        except UnicodeEncodeError:
            return False
        owner_event: threading.Event | None = None
        share = True
        while True:
            with self._lock:
                if generation != self._generation or self._configuration is None:
                    return False
                now = self._clock()
                for expired_key, expires in tuple(self._successes.items()):
                    if expires <= now:
                        del self._successes[expired_key]
                if key in self._successes:
                    self._successes.move_to_end(key)
                    return True
                pending = self._inflight.get(key) if share else None
                if pending is None:
                    if share and len(self._inflight) < self._max_inflight:
                        owner_event = threading.Event()
                        self._inflight[key] = owner_event
                    break
            # A failure supplies no reusable result: each waiter must check again.
            pending.wait()
            share = False

        try:
            verified = check() is True
            with self._lock:
                if generation != self._generation or self._configuration is None:
                    return False
                if verified:
                    self._successes[key] = self._clock() + self._ttl
                    self._successes.move_to_end(key)
                    while len(self._successes) > self._max_entries:
                        self._successes.popitem(last=False)
                return verified
        finally:
            if owner_event is not None:
                with self._lock:
                    if self._inflight.get(key) is owner_event:
                        del self._inflight[key]
                    owner_event.set()
