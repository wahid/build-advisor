from wiki.parsing import html_to_text

PAGE = """
<div class="mw-parser-output">
  <span class="item-box -gem">
    <span class="header -single">Cast when Damage Taken Support</span>
    <span class="item-stats">
      <span class="group">Support, Spell, Trigger<br/>Level: <em>(1-20)</em></span>
      <span class="group">Requires Level 38</span>
    </span>
  </span>
  <div class="hatnote">For the other version, see X.</div>
  <p>Cast when Damage Taken is a <a href="/wiki/Support">support gem</a>.
  <sup class="reference">[1]</sup></p>
  <div class="mw-heading mw-heading2"><h2 id="Interactions">Interactions</h2></div>
  <ul><li>Cannot support totems.</li><li>Works with auras.</li></ul>
  <h3>Gem level progression</h3>
  <table><tr><th>Level</th><th>Damage</th></tr><tr><td>1</td><td>65% less</td></tr></table>
  <div class="navbox">Navigation junk</div>
  <ol class="references"><li>Source</li></ol>
</div>
"""


def test_keeps_infobox_lines_and_paragraphs() -> None:
    text = html_to_text(PAGE)
    assert text.startswith("Cast when Damage Taken Support")
    assert "Support, Spell, Trigger\nLevel: (1-20)" in text
    assert "Cast when Damage Taken is a support gem." in text


def test_headings_become_markdown_markers() -> None:
    text = html_to_text(PAGE)
    assert "\n## Interactions\n" in text
    assert "\n### Gem level progression\n" in text


def test_lists_and_tables_are_flattened() -> None:
    text = html_to_text(PAGE)
    assert "- Cannot support totems.\n- Works with auras." in text
    assert "Level | Damage\n1 | 65% less" in text


def test_removes_navigation_references_and_hatnotes() -> None:
    text = html_to_text(PAGE)
    assert "Navigation junk" not in text
    assert "[1]" not in text
    assert "Source" not in text
    assert "For the other version" not in text


def test_collapses_blank_lines() -> None:
    assert "\n\n\n" not in html_to_text(PAGE)
