#!/usr/bin/env python3
"""Convert a folder of eBible.org USFM files into a bundled JSON Bible.

Sources (public domain):
    KJV  https://ebible.org/Scriptures/eng-kjv2006_usfm.zip
    ASV  https://ebible.org/Scriptures/eng-asv_usfm.zip

Output shape:
    {"GEN": [ [ {"v": 1, "h": "<verse html>", "p": 1, "t": "title"}, ... ], ... ], ...}
Each book is a list of chapters; each chapter is a list of verses.
  h  verse text as a small, trusted HTML subset (<i>, <br>, <span class="nd|wj">)
  p  1 when the verse begins a new paragraph / poetry line
  t  heading shown above the verse (psalm titles, Psalm 119 letters)

Usage:
    python3 tools/build_usfm.py data/raw/kjv_usfm data/kjv.json
    python3 tools/build_usfm.py data/raw/asv_usfm data/asv.json --red-letters-from data/kjv.json

--red-letters-from copies words-of-Jesus markup from another bundled Bible by
aligning each verse word by word (see tools/red_letters.py). The ASV has no
red-letter edition of its own, so it borrows the KJV's.
"""
import glob
import html
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from bibleref import BOOKS  # noqa: E402
sys.path.insert(0, os.path.join(ROOT, "tools"))
import red_letters  # noqa: E402

BOOK_IDS = {b[0] for b in BOOKS}


def _small_caps(m):
    # LORD -> "Lord" rendered in small caps; "Lord’s", not "Lord’S"
    words = " ".join(w[:1] + w[1:].lower() for w in m.group(1).split(" "))
    return f'<span class="nd">{words}</span>'


CHAR_RULES = [
    (re.compile(r"\\f .*?\\f\*"), ""),                                  # footnotes
    (re.compile(r"\\x .*?\\x\*"), ""),                                  # cross references
    (re.compile(r"\\\+?w ([^\\|]*?)(?:\|[^\\]*)?\\\+?w\*"), r"\1"),     # Strong's-tagged words
    (re.compile(r"\\\+?qs \[?(.*?)\\\+?qs\*"), r"<i>\1</i>"),              # Selah (ASV: "[Selah")
    (re.compile(r"\\\+?(?:add|it) (.*?)\\\+?(?:add|it)\*"), r"<i>\1</i>"),  # supplied words
    (re.compile(r"\\\+?(?:nd|sc) (.*?)\\\+?(?:nd|sc)\*"), _small_caps),  # LORD, inscriptions
    (re.compile(r"\\wj (.*?)\\wj\*"), r'<span class="wj">\1</span>'),   # words of Jesus
    (re.compile(r"\\\+?(?:tl|bd) (.*?)\\\+?(?:tl|bd)\*"), r"\1"),
]

# line markers that start a paragraph or poetry line
BREAKS = {"p", "m", "q1", "q2", "q3", "qc", "pi1", "b"}
# metadata, book titles, introductions and major section headings we drop
DROP = {"h", "toc1", "toc2", "toc3", "mt1", "mt2", "mt3", "mt4", "ms1", "ip", "ib", "is1"}


def inline(text):
    s = html.escape(text, quote=False)
    for _ in range(3):  # markers can nest (\nd inside \wj, \+add inside \nd, ...)
        for pat, rep in CHAR_RULES:
            s = pat.sub(rep, s)
    s = s.replace("¶", "")
    if "\\" in s:
        raise ValueError(f"unhandled USFM marker in: {text!r}")
    s = re.sub(r'(<span class="\w+">|<i>)\s+', r" \1", s)  # keep spaces outside tags
    s = re.sub(r"\s+(</span>|</i>)", r"\1 ", s)
    return re.sub(r"\s+", " ", s).strip()


def convert_book(path):
    book_id = None
    chapters = []
    verse = None
    pending_para = False
    pending_title = None

    def continue_verse(text):
        nonlocal pending_para
        if verse is None or not text:
            return
        verse["h"] += ("<br>" if pending_para else " ") + inline(text)
        pending_para = False

    for raw in open(path, encoding="utf-8-sig"):
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"\\(\w+)\s?(.*)", line)
        marker, rest = (m.group(1), m.group(2)) if m else (None, line)

        if marker == "id":
            book_id = rest.split()[0]
            if book_id not in BOOK_IDS:
                return None, None  # front matter, introductions, apocrypha
        elif marker in DROP:
            pass
        elif marker == "c":
            chapters.append([])
            verse = None
            pending_para = True
        elif marker == "qc" and re.match(r"[\u05d0-\u05ea]", rest):
            pending_title = inline(rest)  # ASV Psalm 119 letters: "\qc ב BETH."
        elif marker in BREAKS:
            pending_para = True
            continue_verse(rest)
        elif marker == "nb":        # "no break": the paragraph carries on
            continue_verse(rest)
        elif marker in ("d", "s1"):
            pending_title = inline(rest)
        elif marker == "v":
            num, _, text = rest.partition(" ")
            verse = {"v": int(num), "h": inline(text)}
            if pending_para:
                verse["p"] = 1
            if pending_title:
                verse["t"] = pending_title
            chapters[-1].append(verse)
            pending_para = False
            pending_title = None
        elif marker is None:
            continue_verse(rest)
        else:
            raise ValueError(f"unhandled line in {path}: {line!r}")

    return book_id, chapters


def add_red_letters(bible, source):
    count = 0
    for bid, chapters in bible.items():
        for ci, chapter in enumerate(chapters):
            prev_red = False
            src_chapter = source[bid][ci] if ci < len(source[bid]) else []
            by_num = {v["v"]: v for v in src_chapter}
            for v in chapter:
                s = by_num.get(v["v"])
                if s and v["h"]:
                    new = red_letters.apply(v["h"], s["h"], continues_red=prev_red)
                    count += new != v["h"]
                    v["h"] = new
                if v["h"]:
                    prev_red = red_letters.ends_red(v["h"])
    return count


def main():
    args = sys.argv[1:]
    red_from = None
    if "--red-letters-from" in args:
        i = args.index("--red-letters-from")
        red_from = args[i + 1]
        del args[i:i + 2]
    if len(args) != 2:
        sys.exit(__doc__)
    src, dest = args
    files = sorted(glob.glob(os.path.join(src, "*.usfm")))
    if not files:
        sys.exit(f"no .usfm files in {src}")
    out = {}
    for f in files:
        book_id, chapters = convert_book(f)
        if book_id:
            out[book_id] = chapters
    missing = BOOK_IDS - set(out)
    if missing:
        sys.exit(f"missing books: {sorted(missing)}")
    if red_from:
        with open(red_from, encoding="utf-8") as fh:
            n = add_red_letters(out, json.load(fh))
        print(f"red letters: {n} verses marked from {red_from}")
    count = sum(len(c) for chs in out.values() for c in chs)
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"wrote {dest}: {len(out)} books, {count} verses")


if __name__ == "__main__":
    main()
