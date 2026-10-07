"""Passage cache for the online translations, kept on disk (SQLite) so it survives
restarts.

The ESV API's terms limit how much of its text may be stored: "You may not locally
store more than 500 verses or one-half of any book of the Bible (whichever is
less)." So for the ESV only (LIMITED):

  * at most MAX_VERSES verses in total, and
  * at most half of any one book (Jude has 25 verses, so at most 12 of Jude).

ESV passages are dropped least-recently-used first to stay inside both limits, and
one too long to store is always fetched live. Overlapping passages (John 3 and
John 3:16) are counted separately, which only ever errs on the side of storing less.
The other translations publish no caching rule, so their cache has no size limit.

Passages are kept forever by default: translations change rarely and only in
minor ways. Setting max_age_days throws away passages older than that, so they're
fetched fresh.
"""
import json
import os
import sqlite3
import sys
import threading
import time

MAX_VERSES = 500
LIMITED = {"ESV"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS passages (
    tid    TEXT NOT NULL,     -- translation id
    ref    TEXT NOT NULL,     -- normalized reference, e.g. "John 3:16-18"
    book   TEXT NOT NULL,     -- book id, for the half-a-book limit
    n      INTEGER NOT NULL,  -- verse count
    result TEXT NOT NULL,     -- the JSON sent to the browser
    fums   TEXT NOT NULL,     -- API.Bible view-report tokens (JSON list)
    time   REAL NOT NULL,     -- when it was fetched
    used   REAL NOT NULL,     -- when it was last shown
    PRIMARY KEY (tid, ref)
);
CREATE INDEX IF NOT EXISTS passages_used ON passages (tid, used);
"""


class PassageCache:
    def __init__(self, path, max_age_days=0):
        self.path = path
        self.max_age = max_age_days * 86400
        self.lock = threading.Lock()
        try:
            fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)  # private, like config.json
            os.close(fd)
            self.db = sqlite3.connect(path, check_same_thread=False)
            self.db.executescript(SCHEMA)
        except (OSError, sqlite3.Error) as e:
            print(f"note: can’t open cache {path} ({e}); keeping it in memory", file=sys.stderr)
            self.db = sqlite3.connect(":memory:", check_same_thread=False)
            self.db.executescript(SCHEMA)
        self._expire()

    def _expire(self):
        if self.max_age:
            with self.lock, self.db:
                self.db.execute("DELETE FROM passages WHERE time < ?", (time.time() - self.max_age,))

    # ------------------------------------------------------------ get / put

    def get(self, tid, ref):
        """(result, fums tokens) for a fresh cached passage, else None."""
        key = (tid, ref.query())
        with self.lock, self.db:
            row = self.db.execute(
                "SELECT result, fums, time FROM passages WHERE tid = ? AND ref = ?", key).fetchone()
            if row is None:
                return None
            if self.max_age and time.time() - row[2] > self.max_age:
                self.db.execute("DELETE FROM passages WHERE tid = ? AND ref = ?", key)
                return None
            self.db.execute("UPDATE passages SET used = ? WHERE tid = ? AND ref = ?",
                            (time.time(), *key))
            return json.loads(row[0]), tuple(json.loads(row[1]))

    def put(self, tid, ref, result, fums):
        n = len(result["verses"])
        book = ref.book.id
        with self.lock, self.db:
            self.db.execute("DELETE FROM passages WHERE tid = ? AND ref = ?", (tid, ref.query()))
            if tid in LIMITED and not self._make_room(tid, book, n, sum(ref.book.verse_counts) // 2):
                return  # too long to store under the limits; always fetched live
            now = time.time()
            self.db.execute(
                "INSERT INTO passages VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (tid, ref.query(), book, n, json.dumps(result, ensure_ascii=False),
                 json.dumps(list(fums)), now, now))

    def _make_room(self, tid, book, n, book_limit):
        """Drop tid's least recently used passages until n more verses fit. False if
        they never can."""
        if n > min(MAX_VERSES, book_limit):
            return False

        def used(in_book):
            sql = "SELECT COALESCE(SUM(n), 0) FROM passages WHERE tid = ?"
            return self.db.execute(sql + (" AND book = ?" if in_book else ""),
                                   (tid, book) if in_book else (tid,)).fetchone()[0]

        while used(False) + n > MAX_VERSES or used(True) + n > book_limit:
            # over the total: any passage helps; only over the book: only that book's
            in_book = used(False) + n <= MAX_VERSES
            sql = "SELECT ref FROM passages WHERE tid = ?"
            args = (tid,)
            if in_book:
                sql += " AND book = ?"
                args = (tid, book)
            oldest = self.db.execute(sql + " ORDER BY used, rowid LIMIT 1", args).fetchone()
            self.db.execute("DELETE FROM passages WHERE tid = ? AND ref = ?", (tid, oldest[0]))
        return True

    def stats(self):
        with self.lock:
            rows = self.db.execute(
                "SELECT tid, COUNT(*), SUM(n) FROM passages GROUP BY tid").fetchall()
        return {tid: {"passages": p, "verses": v} for tid, p, v in rows}
