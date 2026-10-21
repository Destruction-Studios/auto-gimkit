# WRITTEN BY Claude.ai

"""
WordDb: a Latin -> English word database that loads and saves itself
to words.json. Self-contained (no other files needed).

    words = WordDb()                 # loads or creates words.json
    words.add("aqua", "water")       # saved automatically -> "added"
    words.add("aqua", "the water")   # same word, new meaning -> "updated"
    words.get("aqua")                # {"latin": "aqua", "english": "water"}
    words.get("aquaa")               # None (exact matches only)

Lookups are exact, apart from ignoring surrounding whitespace and letter case.

Saves are atomic (temp file + replace), batched (many rapid changes become
one write after `delay` seconds), and anything unsaved is flushed on exit.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Iterator

log = logging.getLogger(__name__)

DEFAULT_PATH = Path(__file__).parent / "words.json"


class WordDb:
    def __init__(
        self,
        path: str | os.PathLike = DEFAULT_PATH,
        delay: float = 0.5,
    ):
        """
        path:   JSON file to read from / write to.
        delay:  seconds to wait before writing after a change. 0 = write
                immediately on every change.
        """
        self.path = Path(path)
        self.delay = delay

        self._lock = threading.RLock()
        self._timer: threading.Timer | None = None
        self._dirty = False
        self._words: dict[str, dict] = self._load()

        atexit.register(self.flush)

    # -- loading / saving -------------------------------------------------

    def _load(self) -> dict:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
            problem = "not a JSON object"
        except FileNotFoundError:
            return {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            problem = "invalid JSON"

        backup = self.path.with_name(self.path.name + ".corrupt")
        os.replace(self.path, backup)
        log.warning("%s was %s, moved to %s and reset", self.path, problem, backup)
        return {}

    def _changed(self) -> None:
        with self._lock:
            self._dirty = True
            if self.delay <= 0:
                self.save()
            elif self._timer is None:
                self._timer = threading.Timer(self.delay, self._timer_save)
                self._timer.daemon = True
                self._timer.start()

    def _timer_save(self) -> None:
        try:
            self.save()
        except Exception:
            log.exception("Autosave to %s failed", self.path)

    def save(self) -> None:
        """Write to disk right now (atomic)."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

            text = json.dumps(self._words, indent=2, ensure_ascii=False)
            self.path.parent.mkdir(parents=True, exist_ok=True)

            fd, tmp = tempfile.mkstemp(
                dir=self.path.parent, prefix=self.path.name + ".", suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(text)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, self.path)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
            self._dirty = False

    def flush(self) -> None:
        """Save only if there are unsaved changes."""
        with self._lock:
            if self._dirty:
                self.save()

    def __enter__(self) -> "WordDb":
        return self

    def __exit__(self, *exc) -> None:
        self.flush()

    # -- words ------------------------------------------------------------

    @staticmethod
    def _key(latin: str) -> str:
        """Normalise a word for lookup: trimmed and lowercase."""
        return latin.strip().lower()

    def add(self, latin: str, english: str) -> str:
        """
        Save a word. If the exact word is already stored, its entry is
        overwritten with the new meaning.

        Returns "added", "updated" (the word existed with a different
        meaning), or "unchanged" (already stored exactly like this).
        """
        latin = self._key(latin)
        new_entry = {"latin": latin, "english": english.strip().lower()}

        with self._lock:
            old_entry = self._words.get(latin)

            if old_entry is None:
                status = "added"
            elif old_entry == new_entry:
                return "unchanged"
            else:
                status = "updated"

            self._words[latin] = new_entry
            self._changed()
            return status

    def get(self, latin: str) -> dict | None:
        with self._lock:
            entry = self._words.get(self._key(latin))
            return entry.copy() if entry else None

    def remove(self, latin: str) -> bool:
        with self._lock:
            key = self._key(latin)
            if key not in self._words:
                return False
            del self._words[key]
            self._changed()
            return True

    def __contains__(self, latin: str) -> bool:
        return self._key(latin) in self._words

    def __len__(self) -> int:
        return len(self._words)

    def __iter__(self) -> Iterator[str]:
        return iter(list(self._words))