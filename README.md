# Bible Lookup

A small Bible passage lookup site you run on your own computer or home server.
There is also a [Mac app version](https://github.com/davidluttrull/bible-lookup-mac).

```
git clone https://github.com/davidluttrull/bible-lookup-web.git
cd bible-lookup-web
python3 server.py
```

Then open <http://localhost:8321>. Type a reference (`John 3:16`, `jn 3:16-18`,
`Ps 23`, `1 Cor 13`, `Jude 5`), pick a translation, and press Enter. Press `/`
to jump to the search box from anywhere.

Separate several passages with semicolons: `James 1:5; John 3:16-18`. A part
without a book name continues the previous book, so `John 3:16; 4:2` shows
John 3:16 and John 4:2.

It needs only Python 3; there are no packages to install. Run this way, the
server listens on `localhost` only, so nothing is exposed to the network. Your
API keys never leave the server either way.

## Running it in Docker

The repository includes a `Dockerfile` and `docker-compose.yml`. On the server:

```
git clone https://github.com/davidluttrull/bible-lookup-web.git
cd bible-lookup-web
mkdir -p config
cp config.example.json config/config.json   # then add your keys
docker compose up -d --build
```

Then open `http://<server>:8321`. To use another port, change the left number
under `ports:` in `docker-compose.yml`.

- **Config:** `config/config.json` holds your API keys and API.Bible IDs. It's
  mounted into the container and is never copied into the image. You can put the
  keys in `environment:` in `docker-compose.yml` instead. Environment keys take
  priority and are never written to the file.
- **Permissions:** the container runs as user ID 1000. If `--setup` can't save,
  run `sudo chown -R 1000:1000 config` on the server. The site still runs with a
  read-only config folder.
- **Commands inside the container:**
  ```
  docker compose exec bible-lookup python server.py --check ESV
  docker compose exec bible-lookup python server.py --setup
  docker compose restart
  ```
- **Updating:** run `git pull`, then `docker compose up -d --build`.
- **Who can use it:** anyone who can reach the server can look up passages, and
  their lookups count against your ESV and API.Bible limits. Keep it on your home
  network, or put it behind a login before exposing it to the internet.
- **Open in Logos** links open Logos on whichever computer you're browsing from.
  The server doesn't need Logos.

## Where the text comes from

Logos stores its Bibles encrypted and licensed to the Logos app. They can't
be read by other programs, so every passage has an **Open in Logos** link that
opens it in your licensed Logos copy.

| Translation | Source | Setup |
|---|---|---|
| KJV, ASV | Bundled in `data/kjv.json` and `data/asv.json` (public domain, from eBible.org) | none; works offline |
| NET | labs.bible.org | none |
| NLT | api.nlt.to | works now on the shared `TEST` key; get your own free key for regular use |
| ESV | api.esv.org | free key |
| NIV, CSB, NASB | API.Bible | free Starter plan, 3 copyrighted Bibles of your choice |

Translations without a source still appear in the picker. They show links to
Logos and BibleGateway in place of the text.

Section headings (like "You Must Be Born Again" before John 3) appear for the
translations whose source sends them: ESV, NLT, NIV, CSB and NASB. The KJV and
ASV files have none, and the NET API leaves them out.

### ESV (free key)

1. Sign in at <https://api.esv.org/account/create-application/> and create an
   application (non-commercial, personal use).
2. Paste the key into `config.json` as `"esv_api_key"`.

### NLT (free key)

1. Request a key at <https://api.nlt.to/>.
2. Paste it into `config.json` as `"nlt_api_key"`.

### NIV, CSB, NASB (API.Bible)

1. Sign up at <https://api.bible>. The free **Starter** plan lets you pick
   3 copyrighted Bibles (non-commercial, 5,000 calls a month). The **Pro** plan
   ($29+/month) includes the rest.
2. Choose your translations in the API.Bible dashboard.
3. Paste the key into `config.json` as `"api_bible_key"`.
4. Run `python3 server.py --setup`. It finds the Bible IDs your key can read and
   saves them to `config.json`.

Restart the server after any change to `config.json`.

API.Bible asks apps to report which passages are shown (its Fair Use Management
System). The server does this in the background for each API.Bible passage,
using a random device ID in `config.json` and no personal information.

## Testing a translation

```
python3 server.py --check ESV     # or NIV, CSB, NLT, NET, KJV, ...
```

This runs seven sample passages (a single verse, ranges, a cross-chapter range,
poetry, a full chapter, a one-chapter book, and 3 John 1:15) and reports ✓ or ✗
for each. Run it after adding or changing a key.

## Files

- `config.example.json`: blank settings. `python3 server.py` creates `config.json`
  from these defaults on its first run; your keys go there, and git ignores it.
- `server.py`: web server and API (`/api/config`, `/api/passage?q=…&t=…`)
- `providers.py`: one class per text source
- `bibleref.py`: book names, abbreviations, and reference parsing
- `static/`: the web page (HTML, CSS, JS)
- `tools/build_usfm.py`: rebuilds the bundled Bibles from eBible's USFM files
  (`python3 tools/build_usfm.py data/raw/asv_usfm data/asv.json --red-letters-from data/kjv.json`)
- `tools/red_letters.py`: the ASV has no red-letter edition, so its words of
  Jesus are carried over from the KJV by lining up each verse word by word.
  Checked against the World English Bible's own red letters (an independent
  source): they agree on 98.7% of words; nearly all differences are places
  where the two editions' editors made different calls.
- `tests/`: run with `python3 -m unittest discover tests`
