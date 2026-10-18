"""Runs the diagnostic scenarios against the production rules and checks
that the inference engine picks the diagnosis chemistry... er, hardware
reality says it should. Mirrors knowledge_base.pl's action/1 rules, but
keeps diagnoses as short atoms (the mini-interpreter has no string literals)
and maps them to the same English text knowledge_base.pl prints."""

from __future__ import annotations

from prolog_engine import KnowledgeBase

# Same five conditions and six rules as knowledge_base.pl's action/1,
# just with atom codes standing in for the double-quoted diagnosis
# strings SWI-Prolog supports and the mini-interpreter does not.
ACTION_RULES = """
action(power_problem) :- \\+ condition(power_present).
action(psu_fault) :- condition(computer_not_start), condition(power_present), condition(fan_not_work).
action(video_fault) :- condition(computer_not_start), condition(power_present), condition(monitor_not_work).
action(motherboard_fault) :- condition(computer_not_start), condition(power_present), \\+ condition(fan_not_work), \\+ condition(monitor_not_work).
action(ram_fault) :- condition(beep_repeating).
action(critical_fault) :- condition(burning_smell).
"""

# Only the two conflicting rules (psu_fault / video_fault), declared in the
# opposite order, used for the rule-order-sensitivity check below.
SWAPPED_CONFLICT_RULES = """
action(video_fault) :- condition(computer_not_start), condition(power_present), condition(monitor_not_work).
action(psu_fault) :- condition(computer_not_start), condition(power_present), condition(fan_not_work).
"""

DIAGNOSIS_TEXT = {
    "power_problem": "There is a power supply problem.",
    "psu_fault": "The power supply unit may be faulty.",
    "video_fault": "There may be a problem with the video card or monitor.",
    "motherboard_fault": "There may be a problem with the motherboard.",
    "ram_fault": "RAM may be faulty (repeating beep code).",
    "critical_fault": "Critical fault: burning smell detected, power off immediately.",
}

# Each scenario: label, asserted conditions, expected conflict set in the
# clause order action/1 declares it (first element = what the interactive
# what_is_problem/0 would print).
SCENARIOS = [
    (
        "no_power",
        ["computer_not_start"],
        ["power_problem"],
        "No power present at all: rule 1 alone fires.",
    ),
    (
        "psu_fault",
        ["computer_not_start", "power_present", "fan_not_work"],
        ["psu_fault"],
        "Power present, fan stopped, monitor fine: rule 2 alone.",
    ),
    (
        "video_fault",
        ["computer_not_start", "power_present", "monitor_not_work"],
        ["video_fault"],
        "Power present, fan fine, monitor blank: rule 3 alone.",
    ),
    (
        "motherboard_fault",
        ["computer_not_start", "power_present"],
        ["motherboard_fault"],
        "Power present, fan and monitor both fine: rule 4 (double negation).",
    ),
    (
        "ram_fault",
        ["power_present", "beep_repeating"],
        ["ram_fault"],
        "Independent symptom: repeating beep code only.",
    ),
    (
        "critical_fault",
        ["power_present", "burning_smell"],
        ["critical_fault"],
        "Independent symptom: burning smell only.",
    ),
    (
        "conflict",
        ["computer_not_start", "power_present", "fan_not_work", "monitor_not_work"],
        ["psu_fault", "video_fault"],
        "Conflict set of size 2: rules 2 and 3 both match. "
        "Declaration order picks rule 2 (psu_fault) first.",
    ),
    (
        "all_symptoms",
        [
            "computer_not_start", "power_present", "fan_not_work",
            "monitor_not_work", "beep_repeating", "burning_smell",
        ],
        ["psu_fault", "video_fault", "ram_fault", "critical_fault"],
        "Conflict set of size 4. Plain declaration order surfaces psu_fault "
        "first even though critical_fault is safety-critical -- a real "
        "weakness of order-only resolution (see answers.md, Q8).",
    ),
]


def build_kb(rules_text: str, conditions: list[str]) -> KnowledgeBase:
    facts = "\n".join(f"condition({c})." for c in conditions)
    return KnowledgeBase.from_text(rules_text + "\n" + facts)


def run_scenarios() -> bool:
    all_passed = True
    for label, conditions, expected, comment in SCENARIOS:
        kb = build_kb(ACTION_RULES, conditions)
        solutions = kb.query("action(X)")
        actual = [str(binding["X"]) for binding in solutions]
        passed = actual == expected
        all_passed &= passed

        print(f"{label}")
        print(f"   conditions: {conditions}")
        print(f"   conflict set ({len(actual)}): "
              f"{[DIAGNOSIS_TEXT[code] for code in actual]}")
        print(f"   {comment}")
        print(f"   [{'ok' if passed else 'MISMATCH'}]")
        print()
    return all_passed


def run_order_experiment() -> bool:
    conflict_conditions = ["computer_not_start", "power_present", "fan_not_work", "monitor_not_work"]

    original = build_kb(ACTION_RULES, conflict_conditions)
    original_first = str(original.query("action(X)")[0]["X"])

    swapped = build_kb(SWAPPED_CONFLICT_RULES, conflict_conditions)
    swapped_first = str(swapped.query("action(X)")[0]["X"])

    passed = original_first != swapped_first
    print("Rule-order experiment (lab step 11):")
    print(f"   original clause order  -> first = {DIAGNOSIS_TEXT[original_first]}")
    print(f"   rules 2 and 3 swapped   -> first = {DIAGNOSIS_TEXT[swapped_first]}")
    print(f"   [{'ok' if passed else 'MISMATCH'}] swapping the two conflicting "
          f"rules changes which diagnosis wins")
    print()
    return passed


def main() -> None:
    print(f"Rule base loaded: {len(SCENARIOS)} scenarios over {ACTION_RULES.count('action(')} production rules")
    print("=" * 70)
    print()

    results = [run_scenarios(), run_order_experiment()]

    print("=" * 70)
    print("ALL CHECKS PASSED" if all(results) else "SOME CHECKS FAILED")


if __name__ == "__main__":
    main()
