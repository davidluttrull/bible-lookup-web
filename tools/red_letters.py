"""Carry red-letter (words of Jesus) markup from one translation onto another.

The ASV has no red-letter edition. It is a revision of the KJV, though, and most
verses share nearly all their words with it, so each ASV verse is aligned word by
word with the KJV verse (difflib) and each ASV word takes the red/black state of
the KJV word it lines up with. Words the ASV adds or rewords take the state of
the KJV words they replace.

Verse html uses the bundled subset: <i>, <br>, <span class="nd|wj">.
"""
import re
from difflib import SequenceMatcher

TOKEN = re.compile(r"(<[^>]+>)|(\s+)|([^<\s]+)")


def _norm(word):
    return re.sub(r"[^a-z0-9]", "", word.lower())


def source_flags(html):
    """[(normalized word, is_red)] for a verse that already has wj spans."""
    out, stack = [], []
    for tag, _space, word in TOKEN.findall(html):
        if tag:
            if tag.startswith("<span"):
                stack.append('class="wj"' in tag)
            elif tag == "</span>" and stack:
                stack.pop()
        elif word and _norm(word):
            out.append((_norm(word), any(stack)))
    return out


def _target_flags(twords, src, continues_red=False):
    """Red/black for each target word.

    Only runs of 2+ matching words (or one long word) are trusted as anchors, since
    a lone "the" or "and" often matches the wrong place. Anchor words copy the
    source's state; the words between two anchors are spread proportionally over
    the matching stretch of the source, so a gap inside Jesus' words stays red and
    a red/black boundary lands where it does in the source.

    continues_red: the previous verse ended in Jesus' words, so lowercase words at
    the start of this verse that lead into a red anchor continue them (Acts 9:5-6).
    """
    tnorms = [_norm(w) for w in twords]
    snorms = [w for w, _ in src]
    sflags = [f for _, f in src]
    sm = SequenceMatcher(None, tnorms, snorms, autojunk=False)
    anchors = [(a, b, n) for a, b, n in sm.get_matching_blocks()
               if n >= 2 or (n == 1 and len(tnorms[a]) >= 6)]
    flags = [False] * len(tnorms)
    ti = sj = 0  # end of the previous anchor in target / source
    prev_flag = None
    for a, b, n in anchors + [(len(tnorms), len(snorms), 0)]:
        gap_t, gap_s = range(ti, a), range(sj, b)
        if gap_t:
            if ti == 0 and continues_red and n and sflags[b] and twords[0][:1].islower():
                for t in gap_t:
                    flags[t] = True
            elif gap_s:
                for k, t in enumerate(gap_t):
                    flags[t] = sflags[gap_s[0] + k * len(gap_s) // len(gap_t)]
            else:
                # target-only words: red only if red on both sides (or on the one side there is)
                nxt = sflags[b] if n else None
                sides = [f for f in (prev_flag, nxt) if f is not None]
                for t in gap_t:
                    flags[t] = bool(sides) and all(sides)
                if prev_flag is False and nxt:
                    # black -> red with extra words in between ("Jesus said unto him,
                    # Again it is written"): the quote starts at a capital after , or :
                    for t in gap_t:
                        if twords[t][:1].isupper() and t > 0 and twords[t - 1][-1:] in ",:":
                            for u in range(t, a):
                                flags[u] = True
                            break
        for k in range(n):
            flags[a + k] = sflags[b + k]
        if n:
            prev_flag = sflags[b + n - 1]
        ti, sj = a + n, b + n
    return flags


def ends_red(html):
    flags = source_flags(html)
    return bool(flags) and flags[-1][1]


def apply(target_html, source_html, continues_red=False):
    """Return target_html with wj spans wherever the source verse has them."""
    src = source_flags(source_html)
    if not any(f for _, f in src) or 'class="wj"' in target_html:
        return target_html
    tokens = TOKEN.findall(target_html)
    word_idx = [i for i, (_t, _s, w) in enumerate(tokens) if w and _norm(w)]
    flags = _target_flags([tokens[i][2] for i in word_idx], src, continues_red)
    red = {}
    for i, f in zip(word_idx, flags):
        red[i] = f
    # punctuation-only tokens ("—") follow the word before them
    last = False
    for i, (_t, _s, w) in enumerate(tokens):
        if w and i in red:
            last = red[i]
        elif w:
            red[i] = last

    def next_red(i):
        # is the next word red, with no tag in between?
        for j in range(i + 1, len(tokens)):
            tag, _space, word = tokens[j]
            if tag:
                return False
            if word:
                return red.get(j, False)
        return False

    out, open_ = [], False
    for i, (tag, space, word) in enumerate(tokens):
        if tag or space:
            out.append(tag or space)
            continue
        if red.get(i) and not open_:
            out.append('<span class="wj">')
            open_ = True
        out.append(word)
        if open_ and not next_red(i):
            out.append("</span>")
            open_ = False
    return "".join(out)
