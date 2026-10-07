"""Section headings ("s") and titles ("t") from each source's HTML (samples trimmed from real responses)."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import providers  # noqa: E402


def marks(verses):
    return [(v["c"], v["v"], v.get("s"), v.get("t")) for v in verses if v.get("s") or v.get("t")]


class ESVTests(unittest.TestCase):
    def parse(self, page):
        p = providers._ESVParser()
        p.feed(page)
        p.close()
        return p.result()

    def test_heading(self):
        verses = self.parse(
            '<h3 id="p43003001_01-1">You Must Be Born Again</h3>'
            '<p class="starts-chapter"><b class="chapter-num" id="v43003001-1">3:1&nbsp;</b>Now there was a man</p>'
            '<p><b class="verse-num" id="v43003002-1">2&nbsp;</b>This man came to Jesus</p>')
        self.assertEqual(marks(verses), [(3, 1, "You Must Be Born Again", None)])
        self.assertEqual(verses[0]["h"], "Now there was a man")

    def test_heading_and_psalm_title(self):
        verses = self.parse(
            '<h3>The <span class="divine-name">Lord</span> Is My Shepherd</h3>'
            '<h4 class="psalm-title">A Psalm of David.</h4>'
            '<p class="block-indent"><span class="line"><b class="chapter-num" id="v19023001-1">23:1&nbsp;</b>'
            'The <span class="divine-name">Lord</span> is my shepherd;</span></p>')
        self.assertEqual(marks(verses), [(23, 1, "The Lord Is My Shepherd", "A Psalm of David.")])
        self.assertEqual(verses[0]["h"], 'The <span class="nd">Lord</span> is my shepherd;')

    def test_empty_heading_ignored(self):
        verses = self.parse('<h3></h3><h3>The Bride Confesses Her Love</h3>'
                            '<p><b class="chapter-num" id="v22001001-1">1:1&nbsp;</b>The Song of Songs</p>')
        self.assertEqual(marks(verses), [(1, 1, "The Bride Confesses Her Love", None)])


class NLTTests(unittest.TestCase):
    def parse(self, page):
        p = providers._NLTParser()
        p.feed(page)
        return p.verses

    def test_heading_inside_verse(self):
        verses = self.parse(
            '<verse_export ch="5" vn="2"><span class="vn">2</span>and he began to teach them.<p></verse_export>'
            '<verse_export ch="5" vn="3">\n<h3 class="subhead">The Beatitudes</h3>\n'
            '<p class="poet1-vn-hd"><span class="vn">3</span><span class="red">“God blesses those who are poor'
            '<a class="a-tn">*</a><span class="tn"><span class="tn-ref">5:3</span> Greek <em>poor in spirit.</em></span></span></p>'
            '</verse_export>')
        self.assertEqual(marks(verses), [(5, 3, "The Beatitudes", None)])
        self.assertEqual(verses[1]["h"], '<span class="wj">“God blesses those who are poor</span>')

    def test_chapter_number_dropped(self):
        verses = self.parse(
            '<verse_export ch="23" vn="1">'
            '<h3 class="chapter-number"><span class="cw">Psalm</span> <span class="cw_ch">23</span></h3>'
            '<h4 class="subhead">The <span class="subhead-sc">Lord</span> Is My Shepherd</h4>'
            '<p class="psa-title">A psalm of David.</p>'
            '<p class="poet1-vn-sp"><span class="vn">1</span>The <span class="sc">Lord</span> is my shepherd;</p>'
            '</verse_export>')
        self.assertEqual(marks(verses), [(23, 1, "The Lord Is My Shepherd", "A psalm of David.")])
        self.assertEqual(verses[0]["h"], 'The <span class="nd">Lord</span> is my shepherd;')


class APIBibleTests(unittest.TestCase):
    def parse(self, page, psalms=False):
        p = providers._USXParser(ms_is_heading=not psalms)
        p.feed(page)
        p.close()
        return p.result()

    def test_section_and_major_headings(self):  # CSB Matthew 5
        verses = self.parse(
            '<p class="ms">The Sermon on the Mount</p>'
            '<p class="m"><span data-sid="MAT 5:1" class="v">1</span>When he saw the crowds, '
            '<span data-sid="MAT 5:2" class="v">2</span>Then he began to teach them, saying: </p>'
            '<p class="r">(Lk 6:20-23)</p>'
            '<p class="s1">The Beatitudes</p>'
            '<p class="qc"><span data-sid="MAT 5:3" class="v">3</span><span class="wj">“Blessed are the poor in spirit,</span></p>')
        self.assertEqual(marks(verses), [(5, 1, "The Sermon on the Mount", None), (5, 3, "The Beatitudes", None)])

    def test_nasb_psalm(self):
        verses = self.parse(
            '<p class="ms">BOOK 2</p><p class="ms">PSALM 42</p>'
            '<p class="s">Thirsting for God in Trouble and Exile.</p>'
            '<p class="ms">For the choir director. A Maskil of the sons of Korah.</p>'
            '<p class="q"><span data-sid="PSA 42:1" class="v">1</span>As the deer pants for the water brooks,</p>',
            psalms=True)
        self.assertEqual(marks(verses), [(42, 1, "BOOK 2\nThirsting for God in Trouble and Exile.",
                                          "For the choir director. A Maskil of the sons of Korah.")])

    def test_csb_acrostic_letter_is_title(self):
        verses = self.parse(
            '<p class="s1">Delight in God’s Word</p>'
            '<p class="s2"><span class="qac">א</span> Aleph</p>'
            '<p class="q1"><span data-sid="PSA 119:1" class="v">1</span>How happy are those</p>',
            psalms=True)
        self.assertEqual(marks(verses), [(119, 1, "Delight in God’s Word", "א Aleph")])


if __name__ == "__main__":
    unittest.main()
