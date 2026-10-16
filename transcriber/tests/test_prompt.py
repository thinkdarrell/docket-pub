import pytest
from transcriber.prompt import VOCABULARY_SENTENCES, PromptBudgetError, build_initial_prompt

ROSTER = ["Darrell O'Quinn", "Valerie Abbott", "Hunter Williams", "Carol Clarke",
          "LaTonya Tate", "Crystal Smitherman", "Wardine Alexander", "Clinton Woods",
          "J.T. Smith"]


def test_roster_names_come_first_then_vocabulary():
    p = build_initial_prompt(ROSTER)
    assert p.startswith("Birmingham City Council. Councilors present are Darrell O'Quinn, Valerie Abbott")
    assert "ALEA" in p and "Woodlawn" in p
    assert p.index("O'Quinn") < p.index("ALEA")


def test_empty_roster_omits_councilors_clause():
    p = build_initial_prompt([])
    assert p.startswith("Birmingham City Council. ")
    assert "ALEA" in p
    assert "Councilors" not in p


def test_prompt_has_no_labelled_list():
    p = build_initial_prompt(ROSTER)
    assert "Terms:" not in p and "Councilors:" not in p
    assert "ALEA, CJI, APC, Alabama Power" not in p
    assert "ALEA" in p and "O'Quinn" in p
    assert p.index("O'Quinn") < p.index("ALEA")


def test_within_budget():
    assert len(build_initial_prompt(ROSTER)) <= 600


def test_vocabulary_is_trimmed_before_roster():
    long_roster = [f"Councilor Namenumber{i:02d} Surnamelong" for i in range(14)]
    p = build_initial_prompt(long_roster, max_chars=600)
    assert len(p) <= 600
    assert all(n in p for n in long_roster)


def test_refuses_when_roster_alone_overflows():
    huge = [f"Councilor Averyveryverylongname{i:03d} Surname" for i in range(40)]
    with pytest.raises(PromptBudgetError):
        build_initial_prompt(huge, max_chars=600)


def test_vocabulary_sentences_are_prose():
    assert len(VOCABULARY_SENTENCES) == len(set(VOCABULARY_SENTENCES))
    for s in VOCABULARY_SENTENCES:
        assert s.endswith("."), s
        assert s.count(",") <= 3, s
        assert "Terms" not in s, s
