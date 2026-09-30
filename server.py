#!/usr/bin/env python3
"""Bible Lookup — a tiny Bible passage website.

    python3 server.py              start the site at http://localhost:8321
    python3 server.py --setup      find your API.Bible translation IDs and save them
    python3 server.py --check ESV  test one translation with sample passages

Environment variables (all optional; used by the Docker image):
    BIBLE_LOOKUP_CONFIG   path to config.json (default: next to this file)
    BIBLE_LOOKUP_HOST     address to listen on (default 127.0.0.1; 0.0.0.0 in Docker)
    BIBLE_LOOKUP_PORT     port (default from config.json, 8321)
    ESV_API_KEY, NLT_API_KEY, API_BIBLE_KEY   override the keys in config.json
"""
import argparse
import json
import mimetypes
import os
import re
import signal
import sys
import threading
import urllib.parse
import uuid
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import providers
from bibleref import Bible, RefError

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(ROOT, "static")
CONFIG_PATH = os.environ.get("BIBLE_LOOKUP_CONFIG") or os.path.join(ROOT, "config.json")
ENV_KEYS = {"esv_api_key": "ESV_API_KEY", "nlt_api_key": "NLT_API_KEY", "api_bible_key": "API_BIBLE_KEY"}

# Order here is the order in the translation picker.
# logos: resource name for "Open in Logos" links (None = not in your Logos library)
# bg:    BibleGateway version code for the fallback link
TRANSLATIONS = [
    {"id": "NIV", "name": "New International Version", "logos": "niv2011", "bg": "NIV"},
    {"id": "ESV", "name": "English Standard Version", "logos": "esv", "bg": "ESV"},
    {"id": "KJV", "name": "King James Version", "logos": "kjv", "bg": "KJV"},
    {"id": "NLT", "name": "New Living Translation", "logos": "nlt", "bg": "NLT"},
    {"id": "CSB", "name": "Christian Standard Bible", "logos": "csb", "bg": "CSB"},
    {"id": "NASB", "name": "New American Standard Bible (1995)", "logos": "nasb95", "bg": "NASB1995"},
    {"id": "NET", "name": "New English Translation", "logos": "gs-netbible", "bg": "NET"},
    {"id": "ASV", "name": "American Standard Version", "logos": "asv", "bg": "ASV"},
]
API_BIBLE_IDS = ["NIV", "CSB", "NASB"]
# bundled public-domain texts: id -> (data file, copyright line)
BUNDLED = {
    "KJV": ("kjv.json", "King James Version. Public domain."),
    "ASV": ("asv.json", "American Standard Version (1901). Public domain."),
}
DEFAULT_TRANSLATION = "KJV"

DEFAULT_CONFIG = {
    "port": 8321,
    "esv_api_key": "",
    "nlt_api_key": "",
    "api_bible_key": "",
    "api_bible": {},
}


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    return cfg


def with_env(cfg):
    """Config plus any keys given as environment variables (never written to disk)."""
    cfg = dict(cfg)
    for field, var in ENV_KEYS.items():
        if os.environ.get(var):
            cfg[field] = os.environ[var]
    return cfg


def save_config(cfg):
    """Write config.json. Returns False (and keeps running) if it isn't writable."""
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH) or ".", exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
            f.write("\n")
        return True
    except OSError as e:
        print(f"note: can’t write {CONFIG_PATH} ({e.strerror}); continuing without saving", file=sys.stderr)
        return False


class App:
    def __init__(self, cfg):
        bundled = {}
        for tid, (fname, _) in BUNDLED.items():
            with open(os.path.join(ROOT, "data", fname), encoding="utf-8") as f:
                bundled[tid] = json.load(f)
        # KJV verse counts are the reference for parsing and validation
        self.bible = Bible({b: [len(c) for c in chs] for b, chs in bundled["KJV"].items()})
        self.cfg = cfg
        self.translations = {}
        for t in TRANSLATIONS:
            t = dict(t)
            tid = t["id"]
            if tid in BUNDLED:
                t["provider"] = providers.LocalBible(bundled[tid], BUNDLED[tid][1])
            elif tid == "ESV":
                t["provider"] = providers.ESV(cfg.get("esv_api_key"))
            elif tid == "NLT":
                t["provider"] = providers.NLT(cfg.get("nlt_api_key"))
            elif tid == "NET":
                t["provider"] = providers.NET()
            else:
                entry = cfg.get("api_bible", {}).get(tid) or {}
                t["provider"] = providers.APIBible(cfg.get("api_bible_key"), entry.get("id"))
            self.translations[tid] = t
        self.cache = OrderedDict()
        self.lock = threading.Lock()
        # anonymous ids for API.Bible's fair-use view reports
        if not cfg.get("fums_device_id"):
            cfg["fums_device_id"] = uuid.uuid4().hex
            file_cfg = load_config()  # save just the id, never keys that came from env vars
            file_cfg["fums_device_id"] = cfg["fums_device_id"]
            save_config(file_cfg)
        self.fums_session = uuid.uuid4().hex

    def report_views(self, tokens):
        if tokens:
            threading.Thread(target=providers.report_fums, daemon=True,
                             args=(tokens, self.cfg["fums_device_id"], self.fums_session)).start()

    def config_payload(self):
        out = []
        for t in self.translations.values():
            ok, reason = t["provider"].available()
            out.append({
                "id": t["id"], "name": t["name"], "available": ok, "reason": reason,
                "source": t["provider"].source, "inLogos": bool(t["logos"]),
            })
        books = [{"id": b.id, "name": b.name, "chapters": b.chapters} for b in self.bible.books]
        return {"translations": out, "books": books, "default": DEFAULT_TRANSLATION}

    def links(self, t, ref):
        q = urllib.parse.quote(ref.query())
        return {
            "logos": f"logosres:{t['logos']};ref=Bible.{ref.logos()}" if t["logos"] else None,
            "bibleGateway": f"https://www.biblegateway.com/passage/?search={q}&version={t['bg']}",
        }

    def ref_payload(self, ref):
        b = ref.book
        name = "Psalm" if b.id == "PSA" and ref.c1 == ref.c2 else b.name
        prev_c = (b, ref.c1 - 1) if ref.c1 > 1 else (
            (self.bible.books[b.index - 1], self.bible.books[b.index - 1].chapters) if b.index > 0 else None)
        next_c = (b, ref.c2 + 1) if ref.c2 < b.chapters else (
            (self.bible.books[b.index + 1], 1) if b.index + 1 < len(self.bible.books) else None)
        return {
            "book": b.id, "bookName": b.name, "c1": ref.c1, "v1": ref.v1, "c2": ref.c2, "v2": ref.v2,
            "isChapter": ref.is_chapter, "query": ref.query(), "display": ref.query(name).replace("-", "–"),
            "chapterQuery": f"{name} {ref.c1}",
            "prev": f"{prev_c[0].name} {prev_c[1]}".replace("Psalms", "Psalm") if prev_c else None,
            "next": f"{next_c[0].name} {next_c[1]}".replace("Psalms", "Psalm") if next_c else None,
        }

    def passage(self, q, tid):
        ref = self.bible.parse(q)  # raises RefError
        t = self.translations.get((tid or "").upper())
        if not t:
            raise RefError(f"Unknown translation “{tid}”.")
        base = {"ref": self.ref_payload(ref), "translation": t["id"], "translationName": t["name"],
                **self.links(t, ref)}
        ok, reason = t["provider"].available()
        if not ok:
            return 200, {**base, "unavailable": reason}
        key = (t["id"], ref)
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                result, tokens = self.cache[key]
                self.report_views(tokens)
                return 200, result
        try:
            verses = t["provider"].fetch(ref)
        except providers.ProviderError as e:
            return 502, {**base, "error": str(e)}
        result = {**base, "verses": verses, "copyright": t["provider"].copyright,
                  "source": t["provider"].source}
        with self.lock:
            self.cache[key] = (result, verses.fums)
            while len(self.cache) > 500:
                self.cache.popitem(last=False)
        self.report_views(verses.fums)
        return 200, result


class Handler(BaseHTTPRequestHandler):
    app: App = None

    def log_message(self, fmt, *args):
        if os.environ.get("BIBLE_LOOKUP_LOG"):
            super().log_message(fmt, *args)

    def send_json(self, status, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path):
        with open(path, "rb") as f:
            body = f.read()
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(url.query)
        if url.path == "/api/config":
            return self.send_json(200, self.app.config_payload())
        if url.path == "/api/parse":
            parts = []
            for text, r in self.app.bible.split(qs.get("q", [""])[0]):
                if isinstance(r, RefError):
                    parts.append({"input": text, "error": str(r)})
                else:
                    name = "Psalm" if r.book.id == "PSA" and r.c1 == r.c2 else None
                    parts.append({"input": text, "query": r.query(name)})
            if not parts:
                return self.send_json(400, {"error": "Type a reference, like John 3:16."})
            return self.send_json(200, {"parts": parts})
        if url.path == "/api/passage":
            try:
                status, obj = self.app.passage(qs.get("q", [""])[0], qs.get("t", [DEFAULT_TRANSLATION])[0])
            except RefError as e:
                status, obj = 400, {"error": str(e)}
            return self.send_json(status, obj)
        if url.path.startswith("/static/"):
            path = os.path.realpath(os.path.join(STATIC, url.path[len("/static/"):]))
            if path.startswith(STATIC + os.sep) and os.path.isfile(path):
                return self.send_file(path)
            return self.send_json(404, {"error": "not found"})
        if url.path.startswith("/api/"):
            return self.send_json(404, {"error": "not found"})
        return self.send_file(os.path.join(STATIC, "index.html"))


# ------------------------------------------------------------------ setup

API_BIBLE_MATCH = {
    "NIV": {"NIV", "NIV11", "NIV2011"},
    "CSB": {"CSB", "CSB17"},
    "NASB": {"NASB", "NASB95", "NASB1995", "NASB20", "NASB2020"},
}


def setup(cfg):
    key = with_env(cfg).get("api_bible_key")
    if not key:
        sys.exit("Put your API.Bible key in config.json as \"api_bible_key\" first "
                 "(sign up free at https://api.bible).")
    body = providers.http_get("https://rest.api.bible/v1/bibles?language=eng", {"api-key": key})
    bibles = json.loads(body)["data"]
    print(f"Your API.Bible key can read {len(bibles)} English Bibles.\n")
    found = {}
    for b in bibles:
        abbrs = {("".join(ch for ch in (b.get(k) or "") if ch.isalnum())).upper()
                 for k in ("abbreviation", "abbreviationLocal")}
        for tid, names in API_BIBLE_MATCH.items():
            if abbrs & names and tid not in found:
                found[tid] = {"id": b["id"], "name": b.get("nameLocal") or b.get("name")}
    for tid in API_BIBLE_IDS:
        if tid in found:
            print(f"  {tid:5} ✓  {found[tid]['name']}  ({found[tid]['id']})")
        else:
            print(f"  {tid:5} –  not on your plan")
    cfg["api_bible"] = found
    if save_config(cfg):
        print(f"\nSaved to {CONFIG_PATH}. Restart the server to pick up the changes.")
    else:
        print("\nCouldn’t save; add this to config.json by hand:\n"
              + json.dumps({"api_bible": found}, indent=2))


# (reference, expected first verse, expected last verse, expected verse count, optional)
# optional: the verse exists only in some translations (3 John 1:15 is in the ESV, not the KJV)
CHECKS = [
    ("John 3:16", (3, 16), (3, 16), 1, False),
    ("John 3:16-18", (3, 16), (3, 18), 3, False),
    ("John 3:36-4:2", (3, 36), (4, 2), 3, False),
    ("Psalm 23", (23, 1), (23, 6), 6, False),
    ("Romans 8", (8, 1), (8, 39), 39, False),
    ("Jude 5", (1, 5), (1, 5), 1, False),
    ("3 John 1:15", (1, 15), (1, 15), 1, True),
]


def check(cfg, tid):
    """Run sample passages through one translation's provider and report problems."""
    app = App(cfg)
    t = app.translations.get(tid.upper())
    if not t:
        sys.exit(f"Unknown translation {tid}. Choose from: {', '.join(app.translations)}")
    ok, reason = t["provider"].available()
    if not ok:
        sys.exit(f"{t['id']} isn’t connected: {reason}")
    print(f"Checking {t['name']} via {t['provider'].source}\n")
    failures = 0
    for q, first, last, count, optional in CHECKS:
        ref = app.bible.parse(q)
        try:
            verses = t["provider"].fetch(ref)
        except providers.ProviderError as e:
            if optional and "not found" in str(e):
                print(f"  – {q:14} not in this translation (fine)")
                continue
            failures += 1
            print(f"  ✗ {q:14} {e}")
            continue
        got = ((verses[0]["c"], verses[0]["v"]), (verses[-1]["c"], verses[-1]["v"]), len(verses))
        good = got == (first, last, count)
        failures += not good
        span = f"{got[0][0]}:{got[0][1]}–{got[1][0]}:{got[1][1]}, {got[2]} verse{'s' * (got[2] != 1)}"
        text = re.sub(r"<[^>]+>", " ", verses[0]["h"])
        text = re.sub(r"\s+", " ", text).strip()
        print(f"  {'✓' if good else '✗'} {q:14} {span:22} “{text[:60]}…”")
        if not good:
            print(f"      expected {first[0]}:{first[1]}–{last[0]}:{last[1]}, {count} verses")
    print("\nAll good." if not failures else f"\n{failures} problem(s). Copy this output to Claude.")
    sys.exit(1 if failures else 0)


def _stop(*_):
    raise KeyboardInterrupt


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--setup", action="store_true", help="look up API.Bible translation IDs")
    ap.add_argument("--check", metavar="TRANSLATION", help="test a translation with sample passages, e.g. --check ESV")
    ap.add_argument("--port", type=int, help="port to listen on (default from config.json, 8321)")
    args = ap.parse_args()

    file_cfg = load_config()
    if not os.path.exists(CONFIG_PATH):
        save_config(file_cfg)
    if args.setup:
        return setup(file_cfg)
    cfg = with_env(file_cfg)
    if args.check:
        return check(cfg, args.check)

    Handler.app = App(cfg)
    host = os.environ.get("BIBLE_LOOKUP_HOST", "127.0.0.1")
    port = args.port or int(os.environ.get("BIBLE_LOOKUP_PORT") or cfg.get("port", 8321))
    try:
        server = ThreadingHTTPServer((host, port), Handler)
    except OSError as e:
        sys.exit(f"Can’t listen on {host}:{port} ({e.strerror}). Is Bible Lookup already running?")
    # `docker stop` sends SIGTERM; shut down the same way as Ctrl+C
    signal.signal(signal.SIGTERM, _stop)
    shown = "localhost" if host in ("127.0.0.1", "0.0.0.0") else host
    print(f"Bible Lookup running at http://{shown}:{port}  (listening on {host}; Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
