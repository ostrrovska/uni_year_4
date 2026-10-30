"""Runs the queries against knowledge_base.pl and checks that the frame
system returns exactly the slot values the model requires.

Answers are compared in the order the engine produces them, not as sets:
in a frame model the order is the result, because the frame's own value is
always found before the inherited one and therefore shadows it."""

from __future__ import annotations

from pathlib import Path

from prolog_engine import KnowledgeBase

KB_PATH = Path(__file__).with_name("knowledge_base.pl")

# Each query is paired with the answers the model requires, so the run is a
# verification and not just a printout.
QUERIES = [
    (
        "query(kitchen_1, area, V)", "V",
        "Own value 18 comes first and shadows the 14 inherited from the class kitchen.",
        ["18", "14"],
    ),
    (
        "query(living_room_1, area, V)", "V",
        "No own area slot, so the only answer is inherited from the class living_room.",
        ["24"],
    ),
    (
        "query(wall_a, comment, V)", "V",
        "Three steps of inheritance: wall_a isa wall, wall ako structural_element, "
        "structural_element ako building_element.",
        ["structural_part_of_a_house"],
    ),
    (
        "query(window_1, glazing, V)", "V",
        "A typical default value taken from the class window.",
        ["double"],
    ),
    (
        "query(house_1, floors, V)", "V",
        "Two levels of override: cottage says 2, the more general house says 1.",
        ["2", "1"],
    ),
    (
        "query(wall_b, material, V)", "V",
        "The nearest ancestor wins: brick from wall, then concrete from structural_element.",
        ["brick", "concrete"],
    ),
    (
        "query(window_1, width, V)", "V",
        "A wider window than its class default: 160 is its own, 140 is inherited.",
        ["160", "140"],
    ),
    (
        "inherited_slot(bedroom_1, purpose, V)", "V",
        "Only values the frame does not store itself.",
        ["sleeping"],
    ),
    (
        "component_of(window_1, X)", "X",
        "Transitive PART-OF through the part_of slot: the window belongs to the "
        "wall and to the house.",
        ["wall_a", "house_1"],
    ),
    (
        "instance_of(kitchen_1, X)", "X",
        "The class of the object and every concept above it, nearest first.",
        ["kitchen", "room_space", "building_element"],
    ),
    (
        "category_of(house_1, C)", "C",
        "Computing demon: the category is derived from area 180, it is stored in no slot.",
        ["medium"],
    ),
]

# Ground goals: no variables, so the answer is simply true or false.
CHECKS = [
    (
        "query(wall_a, load_bearing, yes)", True,
        "Inherited two levels up, from structural_element.",
    ),
    (
        "query(window_1, glazing, double)", True,
        "The value is reachable...",
    ),
    (
        "own_slot(window_1, glazing, double)", False,
        "...but the window frame itself does not store it.",
    ),
    (
        "own_slot(house_1, floors, 2)", False,
        "house_1 has no floors slot of its own; the 2 comes from cottage.",
    ),
    (
        "component_of(window_1, house_1)", True,
        "Two PART-OF steps chained by the transitive rule.",
    ),
    (
        "instance_of(bathroom_1, building_element)", True,
        "Three steps: bathroom, room_space, building_element.",
    ),
]

# Demon scenarios: goal, variables to report, description, expected answers.
DEMONS = [
    (
        "read_slot(kitchen_1, area, V, S)", ("V", "S"),
        "when-read demon on a normal kitchen: both the own and the inherited area pass.",
        [("18", "ok"), ("14", "ok")],
    ),
    (
        "read_slot(bathroom_1, area, V, S)", ("V", "S"),
        "The own value 4 is flagged as suspicious, the inherited 6 is accepted.",
        [("4", "warning(too_small)"), ("6", "ok")],
    ),
    (
        "read_slot(bedroom_1, purpose, V, S)", ("V", "S"),
        "A slot with no demon attached is read unchecked.",
        [("sleeping", "no_demon")],
    ),
    (
        "read_slot(wall_a, thickness, V, S)", ("V", "S"),
        "Both the own 51 and the inherited 38 satisfy the thickness demon.",
        [("51", "ok"), ("38", "ok")],
    ),
    (
        "write_slot(wall_b, thickness, 10, S)", ("S",),
        "when-write demon refuses a wall thinner than 25 cm.",
        [("error(too_thin)",)],
    ),
    (
        "write_slot(wall_b, thickness, 40, S)", ("S",),
        "The same demon accepts a correct value.",
        [("ok",)],
    ),
    (
        "write_slot(kitchen_1, area, big, S)", ("S",),
        "A non-numeric value is rejected before it could ever be stored.",
        [("error(not_a_number)",)],
    ),
]

# The example from the lab methodology, rewritten in the syntax this file
# uses (lowercase atoms, slot_in/2 instead of member/2, a demon that returns
# a status instead of printing one). Used to show the engine behaves like
# real Prolog rather than being tailored to the house knowledge base.
METHODOLOGY_EXAMPLE = """
frame(creature, [comment-creatures_are_moving]).
frame(monkey, [ako-creature, tall-120, weight-50, tail-yes]).
frame(human,  [ako-creature, tall-170, weight-60, tail-no]).
frame(petrenko, [isa-human, language-ukrainian, hair_colour-dark]).

slot_in(X, [X | _]).
slot_in(X, [_ | Rest]) :- slot_in(X, Rest).

query(ID, Slot, Value) :- frame(ID, Slots), slot_in(Slot-Value, Slots).
query(ID, Slot, Value) :- frame(ID, Slots), slot_in(isa-Class, Slots), query(Class, Slot, Value).
query(ID, Slot, Value) :- frame(ID, Slots), slot_in(ako-Parent, Slots), query(Parent, Slot, Value).

tall_demon(Value, valid) :- number(Value), Value > 0.
tall_demon(Value, invalid) :- number(Value), \\+ Value > 0.
tall_demon(Value, invalid) :- \\+ number(Value).
"""


# ------------------------------------------------------------------
# Runners
# ------------------------------------------------------------------

def run_queries(kb: KnowledgeBase) -> bool:
    every_query_passed = True
    for goal, variable, description, expected in QUERIES:
        answers = [str(binding[variable]) for binding in kb.query(goal)]
        passed = answers == expected
        every_query_passed &= passed

        print(f"?- {goal}.")
        print(f"   {description}")
        for answer in answers:
            print(f"   V = {answer}")
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


def run_demons(kb: KnowledgeBase) -> bool:
    print("Demon procedures:")
    all_passed = True
    for goal, variables, description, expected in DEMONS:
        answers = [
            tuple(str(binding[name]) for name in variables)
            for binding in kb.query(goal)
        ]
        passed = answers == expected
        all_passed &= passed
        print(f"   ?- {goal}.")
        print(f"      {description}")
        for answer in answers:
            print(f"      -> {'-'.join(answer)}")
        print(f"      [{'ok' if passed else 'MISMATCH'}]")
    print()
    return all_passed


def run_frame_summary(kb: KnowledgeBase) -> bool:
    """The lab requires properties for at least 20 frames."""
    frames = [str(binding["F"]) for binding in kb.query("frame(F, _)")]

    print("Own and inherited slots of every frame:")
    for frame in frames:
        own = [str(b["S"]) + "-" + str(b["V"])
               for b in kb.query(f"own_slot({frame}, S, V)")]
        inherited = [str(b["S"]) + "-" + str(b["V"])
                     for b in kb.query(f"inherited_slot({frame}, S, V)")]
        print(f"   {frame}  own {len(own)}: {own}")
        print(f"      inherited {len(inherited)}: {inherited}")

    passed = len(frames) >= 20
    print(f"   [{'ok' if passed else 'MISMATCH'}] {len(frames)} frames described, "
          f"at least 20 required")
    print()
    return passed


def run_engine_self_test() -> bool:
    print("Engine self-test on the example from the lab methodology:")
    kb = KnowledgeBase.from_text(METHODOLOGY_EXAMPLE)
    tall = [str(b["V"]) for b in kb.query("query(petrenko, tall, V)")]
    comment = [str(b["V"]) for b in kb.query("query(petrenko, comment, V)")]
    language = [str(b["V"]) for b in kb.query("query(petrenko, language, V)")]
    valid = kb.holds("tall_demon(170, valid)")
    invalid = kb.holds("tall_demon(0, invalid)")
    passed = (
        tall == ["170"]
        and comment == ["creatures_are_moving"]
        and language == ["ukrainian"]
        and valid
        and invalid
    )
    print(f"   ?- query(petrenko, tall, V).  ->  {tall}  (inherited from human)")
    print(f"   ?- query(petrenko, comment, V).  ->  {comment}  (two levels up)")
    print(f"   ?- query(petrenko, language, V).  ->  {language}  (own slot)")
    print(f"   ?- tall_demon(170, valid).  ->  {str(valid).lower()}")
    print(f"   ?- tall_demon(0, invalid).  ->  {str(invalid).lower()}")
    print(f"   [{'ok' if passed else 'MISMATCH'}] the engine reproduces the "
          f"documented result")
    print()
    return passed


def main() -> None:
    kb = KnowledgeBase.from_file(str(KB_PATH))
    print(f"Knowledge base loaded: {len(kb.clauses)} clauses from {KB_PATH.name}")
    print("=" * 70)
    print()

    results = [
        run_queries(kb),
        run_checks(kb),
        run_demons(kb),
        run_frame_summary(kb),
        run_engine_self_test(),
    ]

    print("=" * 70)
    print("ALL CHECKS PASSED" if all(results) else "SOME CHECKS FAILED")


if __name__ == "__main__":
    main()
