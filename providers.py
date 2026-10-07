"""Where each translation's text comes from.

Every provider turns a Ref into a list of verse dicts:
    {"c": 3, "v": 16, "h": "<trusted html>", "p": True,
     "s": "optional section heading", "t": "optional title (psalm title, speaker...)"}
Verse html only ever contains <i>, <br>, and <span class="nd|wj"> that we build
ourselves; all source text is escaped first.
"""
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

USER_AGENT = "bible-lookup/1.0 (personal use)"
TIMEOUT = 15


class ProviderError(Exception):
    pass


def http_get(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        if e.code in (401, 403):
            raise ProviderError("The API key was rejected. Check it in config.json (or its environment variable).") from e
        if e.code == 429:
            raise ProviderError("Rate limit reached for this translation. Try again later.") from e
        if e.code == 404:
            raise ProviderError("Passage not found in this translation.") from e
        raise ProviderError(f"HTTP {e.code}: {body}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise ProviderError(f"Couldn’t reach the server ({getattr(e, 'reason', e)}).") from e


def clean_space(s):
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"(\s*<br>\s*)+", "<br>", s)
    return re.sub(r"^(<br>)+|(<br>)+$", "", s.strip()).strip()


def small_caps_lord(s):
    """Divine name printed in capitals (LORD, GOD) -> small caps, as in print."""
    return re.sub(r"\b(LORD|GOD)\b", lambda m: f'<span class="nd">{m.group(1).capitalize()}</span>', s)


class Verses(list):
    """A provider's verse list. fums holds API.Bible view-report tokens, if any."""
    fums = ()


def within(ref, verses):
    out = Verses(v for v in verses if ref.contains(v["c"], v["v"]) and v["h"])
    if not out:
        raise ProviderError("Passage not found in this translation.")
    return out


def report_fums(tokens, device_id, session_id):
    """Tell API.Bible's Fair Use Management System that these passages were shown.

    Anonymous (a random device id and a per-run session id). Failures are ignored.
    https://docs.api.bible/guides/fair-use/
    """
    params = [("t", t) for t in tokens] + [("dId", device_id), ("sId", session_id)]
    try:
        http_get("https://fums.api.bible/f3?" + urllib.parse.urlencode(params))
    except ProviderError:
        pass


class _VerseHTML(HTMLParser):
    """Shared machinery for turning a translation's HTML into verse dicts.

    Subclasses map their source's tags onto these calls:
      start_block()        a paragraph or poetry line begins
      start_verse(c, v)    a verse number
      open_span(o, c)      inline markup we keep (red letters, small caps, italics)
      plain_span()         inline markup we ignore (keeps open/close tags paired)
      text(data)           text content
      start_title(heading=True)  a section heading (vs. a psalm-style title)
    Text at the start of a block is held back until we know whether it continues the
    current verse (then it goes on a new line) or leads into the next verse number
    (like the "[[" before Mark 16:9).
    """

    PREFIX_ONLY = re.compile(r"[\s\[\]“‘(]*")

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.verses = []
        self.cur = None
        self.skip = 0            # depth inside an element we drop
        self.in_num = False      # inside the verse-number element
        self.title = None        # collecting a title (psalm title, speaker, note)
        self.pending_title = None
        self.title_is_heading = False
        self.pending_heading = None
        self.block_start = False
        self.pending = ""
        self.closers = []        # one entry per open span

    def _add(self, text):
        self.cur["h"] += small_caps_lord(html.escape(text, quote=False))

    def _flush_pending(self):
        # a new paragraph/line that continues the current verse starts on a new line
        # (a trailing <br> left by a block that ends up empty is trimmed by clean_space)
        if self.block_start and self.cur is not None:
            self.cur["h"] += "<br>"
            self._add(self.pending)
        self.pending = ""
        self.block_start = False

    def start_block(self):
        self._flush_pending()
        self.block_start = True

    def start_verse(self, c, v):
        prefix = self.pending.strip()
        self.cur = {"c": c, "v": v, "h": "", "p": self.block_start}
        if self.pending_heading:
            self.cur["s"] = self.pending_heading
            self.pending_heading = None
        if self.pending_title:
            self.cur["t"] = self.pending_title
            self.pending_title = None
        self.verses.append(self.cur)
        if prefix:
            self._add(prefix)
        self.pending = ""
        self.block_start = False
        self.in_num = True

    def start_title(self, heading=False):
        self.title = ""
        self.title_is_heading = heading

    def end_title(self):
        if self.title is not None and self.title.strip():
            text = re.sub(r"\s+", " ", self.title).strip()
            # several before one verse ("BOOK 2", then the psalm title) stack up
            if self.title_is_heading:
                self.pending_heading = f"{self.pending_heading}\n{text}" if self.pending_heading else text
            else:
                self.pending_title = f"{self.pending_title}\n{text}" if self.pending_title else text
        self.title = None
        self.title_is_heading = False

    def open_span(self, open_html, close_html):
        if self.cur is None or self.title is not None:
            return self.plain_span()
        self._flush_pending()
        self.cur["h"] += open_html
        self.closers.append(close_html)

    def plain_span(self):
        self.closers.append("")

    def close_span(self):
        if self.closers:
            close = self.closers.pop()
            if close and self.cur is not None:
                self.cur["h"] += close

    def text(self, data):
        if self.skip or self.in_num:
            return
        if self.title is not None:
            self.title += data
            return
        data = data.replace("\xa0", " ")
        if self.block_start:
            self.pending += data
            if not self.PREFIX_ONLY.fullmatch(self.pending):
                self._flush_pending()
            return
        if self.cur is not None:
            self._add(data)

    handle_data = text

    def result(self):
        for v in self.verses:
            v["h"] = clean_space(v["h"])
        return self.verses


# ---------------------------------------------------------------- providers

class LocalBible:
    """A public-domain Bible bundled in data/*.json (built by tools/build_usfm.py)."""

    source = "Bundled (public domain)"

    def __init__(self, data, copyright):
        self.data = data
        self.copyright = copyright

    def available(self):
        return True, None

    def fetch(self, ref):
        chapters = self.data[ref.book.id]
        out = []
        for c in range(ref.c1, ref.c2 + 1):
            for v in chapters[c - 1]:
                if ref.contains(c, v["v"]):
                    item = {"c": c, "v": v["v"], "h": v["h"], "p": bool(v.get("p"))}
                    if v.get("t"):
                        item["t"] = v["t"]
                    out.append(item)
        return within(ref, out)


class _ESVParser(_VerseHTML):
    """Pull verses out of the ESV API's HTML.

    Verse markers look like <b class="verse-num" id="v43003016-1"> (book, chapter,
    verse packed into the id). Section headings (h3) become the next verse's
    heading; psalm titles, Psalm 119 letters, Song of Songs speakers and textual
    notes (h4) become its title.
    """

    TITLE_CLASSES = {"psalm-title", "psalm-acrostic-title", "textual-note", "speaker"}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = (a.get("class") or "").split()
        if self.skip:
            if tag != "br":
                self.skip += 1
            return
        if tag == "h4" and not self.TITLE_CLASSES & set(cls):
            self.skip = 1
        elif tag == "h3":
            self.start_title(heading=True)
        elif tag == "h4":
            self.start_title()
        elif tag == "b" and ("verse-num" in cls or "chapter-num" in cls):
            m = re.match(r"v\d{2}(\d{3})(\d{3})", a.get("id", ""))
            if m:
                self.start_verse(int(m.group(1)), int(m.group(2)))
        elif tag == "p":
            self.start_block()
        elif tag == "span" and "line" in cls:
            self.start_block()
            self.plain_span()
        elif tag == "span":
            if "woc" in cls:
                self.open_span('<span class="wj">', "</span>")
            elif "divine-name" in cls:
                self.open_span('<span class="nd">', "</span>")
            elif "selah" in cls:
                self.open_span("<i>", "</i>")
            else:
                self.plain_span()

    def handle_endtag(self, tag):
        if self.skip:
            self.skip -= 1
            return
        if tag in ("h3", "h4"):
            self.end_title()
        elif tag == "b":
            self.in_num = False
        elif tag == "span":
            self.close_span()


class ESV:
    source = "api.esv.org"
    copyright = (
        "Scripture quotations are from the ESV® Bible (The Holy Bible, English Standard "
        "Version®), © 2001 by Crossway, a publishing ministry of Good News Publishers. "
        "Used by permission. All rights reserved."
    )

    def __init__(self, key):
        self.key = key

    def available(self):
        if not self.key:
            return False, "Add a free ESV API key (api.esv.org) to config.json."
        return True, None

    def fetch(self, ref):
        q = ref.query()
        if ref.is_chapter and ref.book.chapters == 1:
            # the ESV API reads "Jude 1" as Jude 1:1 in one-chapter books; ask for every
            # verse (one past the KJV count, for 3 John 1:15; the API stops at the last)
            q = f"{ref.book.name} 1:1-{ref.book.verse_counts[0] + 1}"
        params = {
            "q": q,
            "include-passage-references": "false",
            "include-verse-numbers": "true",
            "include-first-verse-numbers": "true",
            "include-chapter-numbers": "true",
            "include-footnotes": "false",
            "include-footnote-body": "false",
            "include-headings": "true",       # section headings (h3) and psalm titles (h4)
            "include-subheadings": "true",
            "include-short-copyright": "false",
            "include-copyright": "false",
            "include-audio-link": "false",
            "include-book-titles": "false",
            "include-crossrefs": "false",
            "include-surrounding-chapters": "false",
            "include-selahs": "true",
            "wrapping-div": "false",
            "include-css-link": "false",
            "inline-styles": "false",
        }
        url = "https://api.esv.org/v3/passage/html/?" + urllib.parse.urlencode(params)
        data = json.loads(http_get(url, {"Authorization": f"Token {self.key}"}))
        p = _ESVParser()
        p.feed("\n".join(data.get("passages") or []))
        p.close()
        return within(ref, p.result())


class _NLTParser(HTMLParser):
    """Pull verses out of the NLT API's HTML, skipping footnotes.

    Section headings (<h3 class="subhead">) sit inside the verse they come before
    and become its heading; other headings (book/chapter labels) are dropped.
    """

    SKIP_TAGS = {"h1", "h2", "h3", "h4", "h5"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.verses = []
        self.cur = None
        self.skip = 0          # depth inside something we drop
        self.stack = []        # open tags inside the current verse: (tag, emitted_close)
        self.title = None
        self.in_title = False
        self.hdepth = 0        # depth inside a section heading we're collecting
        self.htext = ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class", "") or ""
        if tag == "verse_export":
            self.cur = {"c": int(a["ch"]), "v": int(a["vn"]), "h": "", "p": False}
            self.verses.append(self.cur)
            self.stack = []
            return
        if self.cur is None:
            return
        if self.skip:
            self.skip += 1 if tag not in ("br",) else 0
            return
        if self.hdepth:
            self.hdepth += 1 if tag != "br" else 0
            return
        if tag in ("h3", "h4") and "subhead" in cls.split():
            self.hdepth, self.htext = 1, ""
            return
        if tag in self.SKIP_TAGS or cls in ("vn", "tn", "a-tn") or tag == "a":
            self.skip = 1
            return
        if tag == "p":
            if "psa-title" in cls:
                self.in_title = True
                self.title = ""
            elif self.cur["h"].strip():
                self.cur["h"] += "<br>"
            else:
                self.cur["p"] = True
            self.stack.append((tag, ""))
        elif tag == "span" and cls == "red":
            self.cur["h"] += '<span class="wj">'
            self.stack.append((tag, "</span>"))
        elif tag == "span" and cls in ("sc", "subhead-sc"):
            self.cur["h"] += '<span class="nd">'
            self.stack.append((tag, "</span>"))
        elif tag in ("em", "i"):
            self.cur["h"] += "<i>"
            self.stack.append((tag, "</i>"))
        elif tag == "br":
            self.cur["h"] += "<br>"
        else:
            self.stack.append((tag, ""))

    def handle_endtag(self, tag):
        if self.cur is None:
            return
        if tag == "verse_export":
            for _, close in reversed(self.stack):
                self.cur["h"] += close
            self.cur["h"] = clean_space(self.cur["h"])
            self.cur = None
            return
        if self.skip:
            self.skip -= 1
            return
        if self.hdepth:
            self.hdepth -= 1
            text = re.sub(r"\s+", " ", self.htext).strip()
            if not self.hdepth and text:
                self.cur["s"] = f"{self.cur['s']}\n{text}" if self.cur.get("s") else text
            return
        if self.stack:
            t, close = self.stack.pop()
            self.cur["h"] += close
            if t == "p" and self.in_title:
                self.in_title = False
                if self.title.strip():
                    self.cur["t"] = self.title.strip()

    def handle_data(self, data):
        if self.cur is None or self.skip:
            return
        if self.hdepth:
            self.htext += data
            return
        if self.in_title:
            self.title += data
            return
        self.cur["h"] += html.escape(data, quote=False)


class NLT:
    source = "api.nlt.to"
    copyright = (
        "Scripture quotations are taken from the Holy Bible, New Living Translation, "
        "copyright ©1996, 2004, 2015 by Tyndale House Foundation. Used by permission of "
        "Tyndale House Publishers, Carol Stream, Illinois 60188. All rights reserved."
    )

    def __init__(self, key):
        self.key = key or "TEST"

    def available(self):
        return True, None

    def fetch(self, ref):
        params = {"ref": ref.query(), "version": "NLT", "key": self.key}
        page = http_get("https://api.nlt.to/api/passages?" + urllib.parse.urlencode(params))
        p = _NLTParser()
        p.feed(page)
        return within(ref, p.verses)


class NET:
    source = "labs.bible.org"
    copyright = (
        "Scripture quoted by permission. Quotations designated (NET) are from the NET Bible® "
        "copyright ©1996, 2019 by Biblical Studies Press, L.L.C. http://netbible.com "
        "All rights reserved."
    )

    def available(self):
        return True, None

    def fetch(self, ref):
        params = {"passage": ref.query(), "type": "json", "formatting": "plain"}
        body = http_get("https://labs.bible.org/api/?" + urllib.parse.urlencode(params))
        try:
            rows = json.loads(body)
        except ValueError as e:
            raise ProviderError("Passage not found in this translation.") from e
        verses = []
        for r in rows:
            text = html.escape(r.get("text", ""), quote=False)
            verses.append({
                "c": int(r["chapter"]), "v": int(r["verse"]),
                "h": clean_space(text), "p": bool(r.get("title")) or not verses,
            })
        # labs.bible.org answers a missing verse with the whole chapter; filter it
        return within(ref, verses)


class _USXParser(_VerseHTML):
    """Pull verses out of API.Bible's HTML, which uses USFM/USX style names.

      <span class="v" data-sid="JHN 3:16">16</span>   verse marker
      <p class="p|m|q1|q2|...">                       paragraphs and poetry lines
      <p class="d|qa|sp|iex">                         psalm title, acrostic letter,
                                                      speaker, textual note -> title
      <p class="s1|s2|s3">                            section headings -> heading
                                                      (except CSB's Psalm 119 letters,
                                                      s2 headings holding a qac span,
                                                      which become titles)
      <p class="r|mr|sr|cl|mt...">                    other headings (dropped)
      <span class="wj|nd|sc|add|it|qs">               red letters, LORD, italics
    NASB puts psalm titles in "ms" blocks (next to "PSALM 23" labels, which are
    dropped) and marks LORD as L<span class="sc">ord</span>. Outside the Psalms,
    "ms" is a major section heading (CSB's "The Sermon on the Mount").
    Some texts carry junk from their print sources (CSB: "¥¥¥" dividers, "#" around
    dashes, stray commas in <span class="sup">); those are removed.
    """

    TITLE_BLOCKS = {"d", "qa", "sp", "iex"}
    HEADING = re.compile(r"(s|ms|mt|imt|is)\d*$|r$|mr$|sr$|cl$|cd$|sd\d*$")
    SECTION = re.compile(r"s\d*$")
    ITALIC = {"add", "it", "qs", "em", "bdit"}

    def __init__(self, ms_is_heading=False):
        super().__init__()
        self.ms_is_heading = ms_is_heading
        self.heading = False      # inside a heading block
        self.heading_keep = False # ...that holds an acrostic letter, so keep it as a title
        self.block_ms = False     # ...that is an "ms" block
        self.kinds = []           # kind of each open span: "num", "nd" or "other"

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = (a.get("class") or "").split()
        c0 = cls[0] if cls else ""
        if self.skip:
            self.skip += 1
            return
        if tag == "p":
            if c0 in self.TITLE_BLOCKS:
                self.start_title()
            elif c0 == "ms":         # NASB psalm titles (and "BOOK ONE" style headings)
                self.heading, self.heading_keep, self.block_ms = True, True, True
                self.start_title(heading=self.ms_is_heading)
            elif self.HEADING.match(c0):
                self.heading, self.heading_keep = True, False
                self.start_title(heading=bool(self.SECTION.match(c0)))
            elif c0 != "nb":        # nb = "no break": continues the paragraph
                self.start_block()
        elif tag == "span":
            if "sup" in cls:        # CSB: stray footnote-position commas
                self.skip = 1
                return
            if "v" in cls:
                m = re.search(r"(\d+):(\d+)", a.get("data-sid", ""))
                if m and self.title is None:
                    self.start_verse(int(m.group(1)), int(m.group(2)))
                self.kinds.append("num")
                return
            self.kinds.append("nd" if "nd" in cls or "sc" in cls else "other")
            if "qac" in cls:
                self.heading_keep = True
                self.title_is_heading = False   # acrostic letter: a title, not a heading
                self.plain_span()
            elif "wj" in cls:
                self.open_span('<span class="wj">', "</span>")
            elif "nd" in cls or "sc" in cls:
                self.open_span('<span class="nd">', "</span>")
            elif self.ITALIC & set(cls):
                self.open_span("<i>", "</i>")
            else:
                self.plain_span()

    def handle_endtag(self, tag):
        if self.skip:
            self.skip -= 1
            return
        if tag == "p" and self.title is not None:
            if self.heading and not self.heading_keep and not self.title_is_heading:
                self.title = None
            elif re.fullmatch(r"\s*psalm \d+\.?\s*", self.title, re.I):
                self.title = None   # NASB's "PSALM 23" label
            else:
                if self.block_ms and re.match(r"\s*book\b", self.title, re.I):
                    self.title_is_heading = True   # "BOOK 2" divides the Psalms: a heading
                self.end_title()
            self.heading = self.block_ms = False
        elif tag == "span" and self.kinds:
            if self.kinds.pop() == "num":
                self.in_num = False
            else:
                self.close_span()

    def handle_data(self, data):
        # CSB typesetting codes: "¥¥¥" divider rows, and "\xa0#—\xa0#" around closed dashes
        data = re.sub(r"\s*#—\s*#", "—", data)
        data = re.sub(r"\xa0+—", "—", data)
        data = re.sub(r"¥+|#", "", data)
        if "nd" in self.kinds and data.isupper():
            data = " ".join(w[:1] + w[1:].lower() for w in data.split(" "))  # LORD -> Lord
        self.text(data)


class APIBible:
    source = "API.Bible"

    def __init__(self, key, bible_id):
        self.key = key
        self.bible_id = bible_id
        self.copyright = ""

    def available(self):
        if not self.key:
            return False, "Add an API.Bible key to config.json, then run: python3 server.py --setup"
        if not self.bible_id:
            return False, "Not enabled on your API.Bible account (run: python3 server.py --setup)."
        return True, None

    def _get(self, path, tokens):
        params = {
            "content-type": "html",
            "include-notes": "false",
            "include-titles": "true",   # section headings, psalm titles, etc.
            "include-chapter-numbers": "false",
            "include-verse-numbers": "true",
            "include-verse-spans": "false",
        }
        url = (f"https://rest.api.bible/v1/bibles/{self.bible_id}/{path}?"
               + urllib.parse.urlencode(params))
        body = json.loads(http_get(url, {"api-key": self.key}))
        data, json_meta = body["data"], body.get("meta") or {}
        if data.get("copyright"):
            self.copyright = re.sub(r"\s+", " ", data["copyright"]).strip()
        p = _USXParser(ms_is_heading=not path.split("/")[1].startswith("PSA."))
        p.feed(data.get("content", ""))
        p.close()
        tokens.append(json_meta.get("fumsToken"))
        return p.result()

    def fetch(self, ref):
        b = ref.book
        verses = []
        tokens = []
        if ref.is_chapter:
            for c in range(ref.c1, ref.c2 + 1):
                verses += self._get(f"chapters/{b.id}.{c}", tokens)
        else:
            pid = f"{b.id}.{ref.c1}.{ref.v1}-{b.id}.{ref.c2}.{ref.v2}"
            try:
                verses = self._get(f"passages/{pid}", tokens)
            except ProviderError:
                if ref.v2 <= b.verse_counts[ref.c2 - 1]:
                    raise
                # the extra-verse allowance overshot this translation; retry without it
                pid = f"{b.id}.{ref.c1}.{ref.v1}-{b.id}.{ref.c2}.{ref.v2 - 1}"
                verses = self._get(f"passages/{pid}", tokens)
        result = within(ref, verses)
        result.fums = tuple(t for t in tokens if t)
        return result
