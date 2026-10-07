import json
import os
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bibleref import Bible  # noqa: E402
from passage_cache import MAX_VERSES, PassageCache  # noqa: E402

with open(os.path.join(ROOT, "data", "kjv.json"), encoding="utf-8") as f:
    BIBLE = Bible({b: [len(c) for c in chs] for b, chs in json.load(f).items()})


def result(ref):
    verses = [{"c": c, "v": v, "h": "x", "p": False}
              for c in range(ref.c1, ref.c2 + 1)
              for v in range(1, ref.book.verse_counts[c - 1] + 1) if ref.contains(c, v)]
    return {"verses": verses}


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "cache.db")
        self.cache = PassageCache(self.path)

    def tearDown(self):
        self.dir.cleanup()

    def put(self, q, tid="ESV", fums=()):
        ref = BIBLE.parse(q)
        self.cache.put(tid, ref, result(ref), fums)
        return ref

    def cached(self, q, tid="ESV"):
        return self.cache.get(tid, BIBLE.parse(q)) is not None

    def test_hit_and_fums(self):
        self.put("John 3:16", "NIV", ["tok"])
        hit = self.cache.get("NIV", BIBLE.parse("John 3:16"))
        self.assertEqual(hit[1], ("tok",))
        self.assertFalse(self.cached("John 3:16", "ESV"))

    def test_esv_total_limit(self):
        # Psalm chapters, oldest first; keep adding past 500 verses
        for c in range(1, 60):
            self.put(f"Ps {c}")
        self.assertLessEqual(self.cache.stats()["ESV"]["verses"], MAX_VERSES)
        self.assertTrue(self.cached("Ps 59"))
        self.assertFalse(self.cached("Ps 1"))  # least recently used went first

    def test_lru_order(self):
        for c in range(1, 25):
            self.put(f"Ps {c}")
        self.assertTrue(self.cached("Ps 1"))    # shown again, so now the newest
        for c in range(25, 40):
            self.put(f"Ps {c}")
        self.assertTrue(self.cached("Ps 1"))
        self.assertFalse(self.cached("Ps 2"))

    def test_other_translations_unlimited(self):
        for tid in ("NIV", "CSB", "NLT", "NET"):
            for c in range(1, 60):
                self.put(f"Ps {c}", tid)
            self.put("Jude 1", tid)             # a whole book is fine too
            self.assertEqual(self.cache.stats()[tid]["passages"], 60)
            self.assertTrue(self.cached("Ps 1", tid) and self.cached("Jude 1", tid))

    def test_half_book_limit(self):
        self.put("Jude 1")                      # 25 verses: more than half of Jude
        self.assertFalse(self.cached("Jude 1"))
        self.put("Jude 1:1-8")
        self.put("Jude 1:9-14")                 # 8 + 6 > 12: the first is dropped
        self.assertFalse(self.cached("Jude 1:1-8"))
        self.assertTrue(self.cached("Jude 1:9-14"))
        self.put("John 3")                      # other books are untouched
        self.put("Jude 1", "NIV")               # and other translations aren't limited
        self.assertTrue(self.cached("Jude 1:9-14"))

    def test_survives_restart(self):
        self.put("Lev 16:1-19", "NLT")
        again = PassageCache(self.path)
        self.assertIsNotNone(again.get("NLT", BIBLE.parse("Lev 16:1-19")))
        self.assertEqual(oct(os.stat(self.path).st_mode & 0o777), "0o600")

    def test_expiry(self):
        self.cache = PassageCache(os.path.join(self.dir.name, "expiring.db"), max_age_days=30)
        self.put("John 3:16")
        self.put("John 3:17", "NIV")
        with self.cache.db:
            self.cache.db.execute("UPDATE passages SET time = ?", (time.time() - 31 * 86400,))
        self.assertFalse(self.cached("John 3:16"))
        self.assertFalse(self.cached("John 3:17", "NIV"))

    def test_no_expiry(self):
        forever = PassageCache(os.path.join(self.dir.name, "forever.db"))  # the default
        ref = BIBLE.parse("John 3:16")
        forever.put("NIV", ref, result(ref), ())
        with forever.db:
            forever.db.execute("UPDATE passages SET time = 0")
        self.assertIsNotNone(forever.get("NIV", ref))


if __name__ == "__main__":
    unittest.main()
