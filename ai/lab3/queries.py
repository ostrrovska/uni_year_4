"""Runs the queries against knowledge_base.pl and checks that the inference
engine draws exactly the conclusions chemistry says it should."""

from __future__ import annotations

from pathlib import Path

from prolog_engine import KnowledgeBase

KB_PATH = Path(__file__).with_name("knowledge_base.pl")

# Each query is paired with the set of answers chemistry requires, so the run
# is a verification and not just a printout.
QUERIES = [
    (
        "substance_class(water, X)",
        "To which class does water belong?",
        {"oxide"},
    ),
    (
        "oxide(X)",
        "All oxides: two-element compounds containing oxygen.",
        {"water", "carbon_dioxide", "calcium_oxide"},
    ),
    (
        "acid(X)",
        "All acids. Water contains hydrogen but has no acid residue, so it must be excluded.",
        {"sulfuric_acid", "hydrochloric_acid"},
    ),
    (
        "alkali(X)",
        "Alkalis are soluble bases only: copper_hydroxide is insoluble and must not appear.",
        {"sodium_hydroxide", "potassium_hydroxide"},
    ),
    (
        "salt(X)",
        "Salts: metal cation plus acid residue, no hydroxyl group (negation as failure).",
        {"sodium_chloride", "copper_sulfate", "calcium_carbonate"},
    ),
    (
        "electrolyte(X)",
        "Electrolytes: soluble acids, alkalis and soluble salts.",
        {
            "sulfuric_acid",
            "hydrochloric_acid",
            "sodium_hydroxide",
            "potassium_hydroxide",
            "sodium_chloride",
            "copper_sulfate",
        },
    ),
    (
        "non_electrolyte(X)",
        "Compounds that do not conduct in solution -- derived purely by negation.",
        {
            "water",
            "carbon_dioxide",
            "calcium_oxide",
            "methane",
            "copper_hydroxide",
            "calcium_carbonate",
        },
    ),
    (
        "neutralization(sulfuric_acid, X)",
        "Which bases react with sulfuric acid?",
        {"sodium_hydroxide", "potassium_hydroxide", "copper_hydroxide"},
    ),
    (
        "same_class(sodium_chloride, X)",
        "Other substances of the same class as sodium chloride.",
        {"copper_sulfate", "calcium_carbonate"},
    ),
]

# Ground goals: no variables, so the answer is simply true or false.
CHECKS = [
    ("acid(water)", False, "Water is not an acid, even though it contains hydrogen."),
    ("oxide(water)", True, "Water is hydrogen oxide."),
    ("alkali(copper_hydroxide)", False, "A base, but insoluble, so not an alkali."),
    ("salt(sodium_hydroxide)", False, "A hydroxyl group excludes it from the salts."),
    ("electrolyte(methane)", False, "Methane does not dissociate into ions."),
]

# The example from the lab methodology, used to show the engine behaves like
# real Prolog rather than being tailored to the chemistry knowledge base.
METHODOLOGY_EXAMPLE = """
student(olena).
studies(olena, artificial_intelligence).
passed(olena, laboratory_work_1).

admitted_to_test(X) :-
    student(X),
    studies(X, artificial_intelligence),
    passed(X, laboratory_work_1).
"""


def run_queries(kb: KnowledgeBase) -> bool:
    every_query_passed = True
    for goal, description, expected in QUERIES:
        solutions = kb.query(goal)
        answers = sorted({str(binding["X"]) for binding in solutions})
        passed = set(answers) == expected
        every_query_passed &= passed

        print(f"?- {goal}.")
        print(f"   {description}")
        for answer in answers:
            print(f"   X = {answer}")
        if not answers:
            print("   false.")
        print(f"   [{'ok' if passed else 'MISMATCH'}] {len(answers)} solution(s)")
        print()
    return every_query_passed


def run_checks(kb: KnowledgeBase) -> bool:
    print("Ground goals (true/false):")
    all_passed = True
    for goal, expected, description in CHECKS:
        actual = kb.holds(goal)
        passed = actual == expected
        all_passed &= passed
        print(f"   ?- {goal}.  ->  {str(actual).lower()}   [{'ok' if passed else 'MISMATCH'}]")
        print(f"      {description}")
    print()
    return all_passed


def run_engine_self_test() -> bool:
    print("Engine self-test on the example from the lab methodology:")
    kb = KnowledgeBase.from_text(METHODOLOGY_EXAMPLE)
    admitted = kb.holds("admitted_to_test(olena)")
    unknown = kb.holds("admitted_to_test(petro)")
    passed = admitted and not unknown
    print(f"   ?- admitted_to_test(olena).  ->  {str(admitted).lower()}")
    print(f"   ?- admitted_to_test(petro).  ->  {str(unknown).lower()}")
    print(f"   [{'ok' if passed else 'MISMATCH'}] the engine reproduces the documented result")
    print()
    return passed


def main() -> None:
    kb = KnowledgeBase.from_file(str(KB_PATH))
    print(f"Knowledge base loaded: {len(kb.clauses)} clauses from {KB_PATH.name}")
    print("=" * 70)
    print()

    results = [run_queries(kb), run_checks(kb), run_engine_self_test()]

    print("=" * 70)
    print("ALL CHECKS PASSED" if all(results) else "SOME CHECKS FAILED")


if __name__ == "__main__":
    main()
