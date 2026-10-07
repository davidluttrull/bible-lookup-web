import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bibleref import Bible, RefError  # noqa: E402

with open(os.path.join(ROOT, "data", "kjv.json"), encoding="utf-8") as f:
    BIBLE = Bible({b: [len(c) for c in chs] for b, chs in json.load(f).items()})


def q(s):
    return BIBLE.parse(s).query()


class ParseTests(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(q("John 3:16"), "John 3:16")
        self.assertEqual(q("jn 3:16"), "John 3:16")
        self.assertEqual(q("Jn3.16"), "John 3:16")
        self.assertEqual(q("john 3 16"), "John 3:16")
        self.assertEqual(q("  JOHN   3 : 16 "), "John 3:16")

    def test_ranges(self):
        self.assertEqual(q("John 3:16-18"), "John 3:16-18")
        self.assertEqual(q("John 3:16–18"), "John 3:16-18")
        self.assertEqual(q("John 3:36-4:2"), "John 3:36-4:2")
        self.assertEqual(q("Gen 1-2"), "Genesis 1-2")

    def test_chapters(self):
        self.assertEqual(q("Psalm 23"), "Psalms 23")
        self.assertTrue(BIBLE.parse("Psalm 23").is_chapter)
        self.assertEqual(q("Romans"), "Romans 1")

    def test_numbered_books(self):
        for s in ["1 John 1:9", "1John 1:9", "1jn 1:9", "I John 1:9", "First John 1:9", "1st John 1:9"]:
            self.assertEqual(q(s), "1 John 1:9", s)
        self.assertEqual(q("II Tim 3:16"), "2 Timothy 3:16")
        self.assertEqual(q("3 jn 4"), "3 John 1:4")

    def test_names_and_prefixes(self):
        self.assertEqual(q("Song of Solomon 2:1"), "Song of Songs 2:1")
        self.assertEqual(q("Phil 4:13"), "Philippians 4:13")
        self.assertEqual(q("Phlm 1:4"), "Philemon 1:4")
        self.assertEqual(q("Is 53:5"), "Isaiah 53:5")
        self.assertEqual(q("Isa 53:5"), "Isaiah 53:5")
        self.assertEqual(q("Rev 22:21"), "Revelation 22:21")
        self.assertEqual(q("revel 1:1"), "Revelation 1:1")
        self.assertEqual(q("Ecc 3:1"), "Ecclesiastes 3:1")

    def test_single_chapter_books(self):
        self.assertEqual(q("Jude 5"), "Jude 1:5")
        self.assertEqual(q("Jude 3-5"), "Jude 1:3-5")
        self.assertEqual(q("Jude 1:5"), "Jude 1:5")
        self.assertTrue(BIBLE.parse("Jude 1").is_chapter)
        self.assertTrue(BIBLE.parse("Obadiah").is_chapter)

    def test_versification_allowance(self):
        self.assertEqual(q("3 John 1:15"), "3 John 1:15")  # ESV/NIV have v15
        self.assertEqual(q("John 3:16-99"), "John 3:16-37")  # clamps to KJV count + 1

    def test_errors(self):
        for s in ["", "Hezekiah 3:1", "John 30", "John 3:50", "John 3:18-16", "Psalm 151", "123"]:
            with self.assertRaises(RefError, msg=s):
                BIBLE.parse(s)

    def test_split(self):
        def parts(s):
            return [r.query() if not isinstance(r, RefError) else "ERR" for _, r in BIBLE.split(s)]
        self.assertEqual(parts("James 1:5; John 3:16-18"), ["James 1:5", "John 3:16-18"])
        self.assertEqual(parts("John 3:16; 4:2"), ["John 3:16", "John 4:2"])
        self.assertEqual(parts("John 3:16; 17"), ["John 3:16", "John 17"])
        self.assertEqual(parts("John 3:16; 1 John 1:9; 2:1"), ["John 3:16", "1 John 1:9", "1 John 2:1"])
        self.assertEqual(parts("Hezekiah 1; Ps 23;;"), ["ERR", "Psalms 23"])
        self.assertEqual(parts("John 3:16"), ["John 3:16"])
        self.assertEqual(parts(" ; "), [])

    def test_split_commas(self):
        def parts(s):
            return [r.query() if not isinstance(r, RefError) else "ERR" for _, r in BIBLE.split(s)]
        self.assertEqual(parts("Hebrews 9:23-28; 10:11-14, 18; Hebrews 7:27"),
                         ["Hebrews 9:23-28", "Hebrews 10:11-14", "Hebrews 10:18", "Hebrews 7:27"])
        self.assertEqual(parts("John 3:16, 18-20"), ["John 3:16", "John 3:18-20"])
        self.assertEqual(parts("John 3:16, 4:2"), ["John 3:16", "John 4:2"])
        self.assertEqual(parts("John 3:36-4:2, 5"), ["John 3:36-4:2", "John 4:5"])
        self.assertEqual(parts("Ps 23, 24"), ["Psalms 23", "Psalms 24"])
        self.assertEqual(parts("Jude 3, 5"), ["Jude 1:3", "Jude 1:5"])
        self.assertEqual(parts("John 3:16, Rom 5:8, 6:23"), ["John 3:16", "Romans 5:8", "Romans 6:23"])
        self.assertEqual(parts("John 3:16,, 17 ,"), ["John 3:16", "John 3:17"])
        self.assertEqual(parts("Isa. 53:6,"), ["Isaiah 53:6"])
        self.assertEqual(q("Isa. 53:6,"), "Isaiah 53:6")
        self.assertEqual(q(" ;Isa 53:6 ; "), "Isaiah 53:6")
        self.assertEqual(parts("John 3:16, 99"), ["John 3:16", "ERR"])
        self.assertEqual(len(parts(", ".join(["John 3:16"] * 20))), 12)

    def test_logos(self):
        self.assertEqual(BIBLE.parse("John 3:16").logos(), "Jn3.16")
        self.assertEqual(BIBLE.parse("1 Cor 13").logos(), "1Co13")
        self.assertEqual(BIBLE.parse("John 3:36-4:2").logos(), "Jn3.36-4.2")


if __name__ == "__main__":
    unittest.main()
