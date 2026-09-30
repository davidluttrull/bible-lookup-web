"""Bible book table and reference parsing ("jn 3:16-18" -> Ref)."""
import re
from dataclasses import dataclass

# (USFM id, display name, Logos abbreviation, extra aliases)
BOOKS = [
    ("GEN", "Genesis", "Ge", "gen ge gn"),
    ("EXO", "Exodus", "Ex", "exo ex exod"),
    ("LEV", "Leviticus", "Le", "lev le lv"),
    ("NUM", "Numbers", "Nu", "num nu nm nb"),
    ("DEU", "Deuteronomy", "Dt", "deut deu de dt"),
    ("JOS", "Joshua", "Jos", "josh jos jsh"),
    ("JDG", "Judges", "Jdg", "judg jdg jg jdgs"),
    ("RUT", "Ruth", "Ru", "rth ru rut"),
    ("1SA", "1 Samuel", "1Sa", "1sam 1sa 1sm 1s"),
    ("2SA", "2 Samuel", "2Sa", "2sam 2sa 2sm 2s"),
    ("1KI", "1 Kings", "1Ki", "1kgs 1ki 1kg 1k"),
    ("2KI", "2 Kings", "2Ki", "2kgs 2ki 2kg 2k"),
    ("1CH", "1 Chronicles", "1Ch", "1chr 1ch 1chron"),
    ("2CH", "2 Chronicles", "2Ch", "2chr 2ch 2chron"),
    ("EZR", "Ezra", "Ezr", "ezr"),
    ("NEH", "Nehemiah", "Ne", "neh ne"),
    ("EST", "Esther", "Es", "esth est es"),
    ("JOB", "Job", "Job", "jb"),
    ("PSA", "Psalms", "Ps", "ps psa psalm pss psm pslm"),
    ("PRO", "Proverbs", "Pr", "prov pro pr prv"),
    ("ECC", "Ecclesiastes", "Ec", "eccl ecc ec eccles qoh"),
    ("SNG", "Song of Songs", "So", "song sng sos ss songofsolomon canticles cant"),
    ("ISA", "Isaiah", "Is", "isa is"),
    ("JER", "Jeremiah", "Je", "jer je jr"),
    ("LAM", "Lamentations", "La", "lam la"),
    ("EZK", "Ezekiel", "Eze", "ezek eze ezk"),
    ("DAN", "Daniel", "Da", "dan da dn"),
    ("HOS", "Hosea", "Ho", "hos ho"),
    ("JOL", "Joel", "Joe", "joe jl"),
    ("AMO", "Amos", "Am", "am amo"),
    ("OBA", "Obadiah", "Ob", "obad ob oba"),
    ("JON", "Jonah", "Jon", "jon jnh"),
    ("MIC", "Micah", "Mic", "mic mc"),
    ("NAM", "Nahum", "Na", "nah na"),
    ("HAB", "Habakkuk", "Hab", "hab hb"),
    ("ZEP", "Zephaniah", "Zep", "zeph zep zp"),
    ("HAG", "Haggai", "Hag", "hag hg"),
    ("ZEC", "Zechariah", "Zec", "zech zec zc"),
    ("MAL", "Malachi", "Mal", "mal ml"),
    ("MAT", "Matthew", "Mt", "matt mat mt"),
    ("MRK", "Mark", "Mk", "mrk mar mk mr"),
    ("LUK", "Luke", "Lk", "luk lk lu"),
    ("JHN", "John", "Jn", "joh jhn jn"),
    ("ACT", "Acts", "Ac", "act ac"),
    ("ROM", "Romans", "Ro", "rom ro rm"),
    ("1CO", "1 Corinthians", "1Co", "1cor 1co"),
    ("2CO", "2 Corinthians", "2Co", "2cor 2co"),
    ("GAL", "Galatians", "Ga", "gal ga"),
    ("EPH", "Ephesians", "Eph", "eph ephes"),
    ("PHP", "Philippians", "Php", "phil php pp"),
    ("COL", "Colossians", "Col", "col"),
    ("1TH", "1 Thessalonians", "1Th", "1thess 1thes 1th"),
    ("2TH", "2 Thessalonians", "2Th", "2thess 2thes 2th"),
    ("1TI", "1 Timothy", "1Ti", "1tim 1ti 1tm"),
    ("2TI", "2 Timothy", "2Ti", "2tim 2ti 2tm"),
    ("TIT", "Titus", "Tt", "tit ti"),
    ("PHM", "Philemon", "Phm", "philem phm phlm phile"),
    ("HEB", "Hebrews", "Heb", "heb"),
    ("JAS", "James", "Jas", "jas jm jam"),
    ("1PE", "1 Peter", "1Pe", "1pet 1pe 1pt 1p"),
    ("2PE", "2 Peter", "2Pe", "2pet 2pe 2pt 2p"),
    ("1JN", "1 John", "1Jn", "1jn 1jo 1joh 1jhn 1j"),
    ("2JN", "2 John", "2Jn", "2jn 2jo 2joh 2jhn 2j"),
    ("3JN", "3 John", "3Jn", "3jn 3jo 3joh 3jhn 3j"),
    ("JUD", "Jude", "Jud", "jud jd"),
    ("REV", "Revelation", "Re", "rev re rv revelations apocalypse"),
]


@dataclass(frozen=True)
class Book:
    id: str
    name: str
    logos: str
    index: int
    verse_counts: tuple  # verses per chapter (KJV versification)

    @property
    def chapters(self):
        return len(self.verse_counts)


@dataclass(frozen=True)
class Ref:
    book: Book
    c1: int
    v1: int | None  # None = whole chapter(s)
    c2: int
    v2: int | None

    @property
    def is_chapter(self):
        return self.v1 is None

    def contains(self, c, v):
        start = (self.c1, self.v1 or 1)
        end = (self.c2, self.v2 if self.v2 is not None else 10**6)
        return start <= (c, v) <= end

    def query(self, name=None):
        """Plain reference string, e.g. 'John 3:16-18', 'John 3:36-4:2', 'John 3'."""
        name = name or self.book.name
        if self.v1 is None:
            return f"{name} {self.c1}" + (f"-{self.c2}" if self.c2 != self.c1 else "")
        s = f"{name} {self.c1}:{self.v1}"
        if self.c2 != self.c1:
            s += f"-{self.c2}:{self.v2}"
        elif self.v2 != self.v1:
            s += f"-{self.v2}"
        return s

    def logos(self):
        """Logos reference, e.g. 'Jn3.16-18'."""
        b = self.book.logos
        if self.v1 is None:
            return f"{b}{self.c1}" + (f"-{self.c2}" if self.c2 != self.c1 else "")
        s = f"{b}{self.c1}.{self.v1}"
        if self.c2 != self.c1:
            s += f"-{self.c2}.{self.v2}"
        elif self.v2 != self.v1:
            s += f"-{self.v2}"
        return s


class RefError(ValueError):
    pass


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


_ORDINALS = [
    (re.compile(r"^(?:iii|third|3rd)[\s.]+", re.I), "3"),
    (re.compile(r"^(?:ii|second|2nd)[\s.]+", re.I), "2"),
    (re.compile(r"^(?:i|first|1st)[\s.]+", re.I), "1"),
]

_NUMS = re.compile(
    r"(\d+)(?:\s*[:.]\s*(\d+)|\s+(\d+))?"          # chapter, optional :verse (or "3 16")
    r"(?:\s*[-‐-―]\s*(\d+)(?:\s*[:.]\s*(\d+))?)?"  # optional -end
)


class Bible:
    """Book lookup + reference parsing, using KJV verse counts for validation."""

    def __init__(self, verse_counts):
        self.books = []
        self.by_id = {}
        self._alias = {}
        for i, (bid, name, logos, aliases) in enumerate(BOOKS):
            book = Book(bid, name, logos, i, tuple(verse_counts[bid]))
            self.books.append(book)
            self.by_id[bid] = book
            for a in [name, bid, *aliases.split()]:
                self._alias.setdefault(_norm(a), book)

    def find_book(self, text):
        t = text.strip()
        for pat, num in _ORDINALS:
            t = pat.sub(num, t)
        key = _norm(t)
        if not key:
            return None
        if key in self._alias:
            return self._alias[key]
        for book in self.books:  # unique-enough prefix, canonical order wins
            if _norm(book.name).startswith(key):
                return book
        return None

    def parse(self, q):
        q = (q or "").strip()
        if not q:
            raise RefError("Type a reference, like John 3:16.")
        m = re.match(r"^(.*?[a-zA-Z].*?)\s*(\d[\d\s:.\-‐-―]*)?$", q)
        if not m:
            raise RefError(f"Couldn’t understand “{q}”. Try something like John 3:16.")
        book = self.find_book(m.group(1))
        if not book:
            raise RefError(f"Couldn’t find a book called “{m.group(1).strip()}”.")
        nums = (m.group(2) or "").strip().rstrip(":.-")
        if not nums:
            return self._make(book, 1, None, 1, None)
        n = _NUMS.fullmatch(nums)
        if not n:
            raise RefError(f"Couldn’t understand “{nums}”. Try something like {book.name} 3:16.")
        c1 = int(n.group(1))
        v1 = n.group(2) or n.group(3)
        v1 = int(v1) if v1 else None
        x = int(n.group(4)) if n.group(4) else None
        y = int(n.group(5)) if n.group(5) else None

        if book.chapters == 1 and v1 is None and y is None and not (c1 == 1 and x is None):
            # "Jude 5" / "Jude 3-5" mean verses in single-chapter books
            return self._make(book, 1, c1, 1, x or c1)
        if v1 is None:
            if x is None:
                return self._make(book, c1, None, c1, None)
            if y is None:
                return self._make(book, c1, None, x, None)
            return self._make(book, c1, 1, x, y)
        if x is None:
            return self._make(book, c1, v1, c1, v1)
        if y is None:
            return self._make(book, c1, v1, c1, x)
        return self._make(book, c1, v1, x, y)

    def split(self, q, limit=12):
        """Parse "James 1:5; John 3:16-18" into [(text, Ref or RefError), ...].

        A part with no book name continues the previous book, so
        "John 3:16; 4:2" means John 3:16 and John 4:2.
        """
        out = []
        prev = None
        for part in [p.strip() for p in (q or "").split(";") if p.strip()][:limit]:
            try:
                ref = self.parse(part)
            except RefError as e:
                if not (prev and part[0].isdigit()):
                    out.append((part, e))
                    continue
                try:
                    ref = self.parse(f"{prev.book.name} {part}")
                except RefError as e2:
                    out.append((part, e2))
                    continue
            out.append((part, ref))
            prev = ref
        return out

    def _make(self, book, c1, v1, c2, v2):
        def check_ch(c):
            if not 1 <= c <= book.chapters:
                raise RefError(
                    f"{book.name} has only {book.chapters} chapter{'s' if book.chapters > 1 else ''}."
                )

        check_ch(c1)
        check_ch(c2)
        if c2 < c1:
            raise RefError("The end of the range comes before the start.")
        if v1 is not None:
            # allow one extra verse: some modern translations number one more
            # verse than the KJV (e.g. 3 John 1:15, Revelation 12:18)
            limit = book.verse_counts[c1 - 1] + 1
            if not 1 <= v1 <= limit:
                raise RefError(f"{book.name} {c1} has only {limit - 1} verses.")
            if c2 == c1 and v2 < v1:
                raise RefError("The end of the range comes before the start.")
            v2 = min(v2, book.verse_counts[c2 - 1] + 1)
        return Ref(book, c1, v1, c2, v2)
