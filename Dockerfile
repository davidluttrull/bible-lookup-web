# Bible Lookup: small Bible passage website (Python standard library only)
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    BIBLE_LOOKUP_HOST=0.0.0.0 \
    BIBLE_LOOKUP_PORT=8321 \
    BIBLE_LOOKUP_CONFIG=/config/config.json

WORKDIR /app
RUN useradd --uid 1000 --no-create-home --shell /usr/sbin/nologin app \
    && mkdir /config && chown app /config

COPY server.py providers.py bibleref.py ./
COPY static/ static/
COPY data/kjv.json data/asv.json data/

USER app
EXPOSE 8321
VOLUME /config

HEALTHCHECK --interval=60s --timeout=5s --start-period=10s \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/config' % os.environ['BIBLE_LOOKUP_PORT'], timeout=4)"

CMD ["python", "server.py"]
