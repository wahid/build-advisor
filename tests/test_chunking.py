from wiki.chunking import chunk_text

TEXT = """Righteous Fire
Spell, AoE, Fire

Righteous Fire is a spell that burns you and nearby enemies.

## Skill functions and interactions

Degen scales with maximum life and fire resistance.

### With Chieftain

The Chieftain ascendancy is common with this skill.

## Version history

0.11.0 | Added to the game as a new skill gem.

## References

1. Some citation
"""


def test_one_chunk_per_section_with_title_and_path() -> None:
    chunks = chunk_text("Righteous Fire", TEXT, max_chars=1500)

    assert [c.section for c in chunks] == [
        "",
        "Skill functions and interactions",
        "Skill functions and interactions > With Chieftain",
        "Version history",
    ]
    assert chunks[0].text.startswith("Righteous Fire\n\nRighteous Fire\nSpell, AoE, Fire")
    assert chunks[2].text.startswith(
        "Righteous Fire — Skill functions and interactions > With Chieftain\n\n"
    )
    assert [c.position for c in chunks] == [0, 1, 2, 3]


def test_skips_reference_sections_and_tiny_sections() -> None:
    chunks = chunk_text("Righteous Fire", TEXT + "\n## Trivia\n\nShort.\n")

    sections = {c.section for c in chunks}
    assert "References" not in sections
    assert "Trivia" not in sections


def test_long_sections_split_on_paragraphs_within_budget() -> None:
    paragraphs = [f"Paragraph {i} " + "word " * 60 for i in range(10)]
    text = "## Mechanics\n\n" + "\n\n".join(paragraphs)

    chunks = chunk_text("Ignite", text, max_chars=800)

    assert len(chunks) > 1
    assert all(len(c.text) <= 800 for c in chunks)
    assert all(c.section == "Mechanics" for c in chunks)
    body = " ".join(c.text.split("\n\n", 1)[1] for c in chunks)
    assert all(f"Paragraph {i} " in body for i in range(10))


def test_hard_wraps_a_single_huge_paragraph() -> None:
    text = "## Table\n\n" + "\n".join(f"{i} | value" for i in range(500))

    chunks = chunk_text("Gem", text, max_chars=500)

    assert all(len(c.text) <= 500 for c in chunks)
    assert chunks[-1].text.endswith("499 | value")
