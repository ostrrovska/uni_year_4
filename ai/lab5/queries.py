"""Runs the queries against knowledge_base.pl and checks that the inference
engine walks the semantic network exactly the way the domain requires.

The derivation paths (lab step 9) are rebuilt here by stepping through the
is_a / ako / part_of links one query at a time: the mini-interpreter has no
lists, so the path cannot be collected inside Prolog as demo.pl does it."""

from __future__ import annotations

from pathlib import Path

from prolog_engine import KnowledgeBase

KB_PATH = Path(__file__).with_name("knowledge_base.pl")

# Each query is paired with the set of answers the domain requires, so the run
# is a verification and not just a printout.
QUERIES = [
    (
        "inherited_property(sofa_1, X)",
        "Everything the sofa knows about itself: only three_seater is its own.",
        {
            "for_sitting", "has_price", "has_seat", "movable",
            "occupies_space", "seats_several", "soft", "three_seater",
        },
    ),
    (
        "furniture_in(living_room_1, X)",
        "Furniture in the living room: tv_1 and lamp_1 are appliances, so excluded.",
        {
            "armchair_1", "chair_2", "chest_of_drawers_1",
            "coffee_table_1", "dining_table_1", "sofa_1",
        },
    ),
    (
        "component_of(cushion_cover_1, X)",
        "Transitive PART-OF: the cover belongs to the cushion and to the sofa.",
        {"cushion_1", "sofa_1"},
    ),
    (
        "in_room(lamp_1, X)",
        "The lamp has no located_in fact: its room comes through stands_on.",
        {"living_room_1"},
    ),
    (
        "soft_furniture(X)",
        "Classes and objects alike inherit the property soft.",
        {"armchair", "armchair_1", "sofa", "sofa_1"},
    ),
    (
        "needs_power(X)",
        "Inherited from the class appliance, stored on no single object.",
        {"appliance", "lamp", "lamp_1", "tv", "tv_1"},
    ),
    (
        "subclass_of(X, storage)",
        "Everything below storage, both subclasses and instances.",
        {
            "bookshelf", "bookshelf_1", "chest_of_drawers",
            "chest_of_drawers_1", "wardrobe", "wardrobe_1",
        },
    ),
    (
        "made_of(X, wood)",
        "Domain relation 2: a plain fact lookup, no inference involved.",
        {
            "bed_1", "bookshelf_1", "chair_1", "chest_of_drawers_1",
            "desk_1", "dining_table_1", "wardrobe_1",
        },
    ),
    (
        "in_room(X, study_1)",
        "The study also contains the drawer and the shelf, through PART-OF.",
        {"bookshelf_1", "chair_1", "desk_1", "drawer_1", "shelf_1"},
    ),
    (
        "easy_to_move(X)",
        "Negation as failure: movable but not inherited as heavy, so the bed "
        "and the wardrobe drop out.",
        {
            "armchair", "armchair_1", "bookshelf", "bookshelf_1", "chair",
            "chair_1", "chair_2", "chest_of_drawers", "chest_of_drawers_1",
            "coffee_table", "coffee_table_1", "desk", "desk_1",
            "dining_table", "dining_table_1", "furniture", "seating",
            "sofa", "sofa_1", "storage", "table",
        },
    ),
]

# Ground goals: no variables, so the answer is simply true or false.
CHECKS = [
    (
        "subclass_of(sofa_1, furniture)", True,
        "Two steps up the hierarchy, stored nowhere as a fact.",
    ),
    (
        "inherited_property(sofa_1, movable)", True,
        "The property sits on furniture; the sofa only inherits it.",
    ),
    (
        "easy_to_move(wardrobe_1)", False,
        "The wardrobe inherits heavy, so negation as failure rejects it.",
    ),
    (
        "soft_furniture(desk_1)", False,
        "No class above the desk carries the property soft.",
    ),
    (
        "in_room(cushion_cover_1, living_room_1)", True,
        "Three links: part_of, part_of, located_in.",
    ),
]

# Derivation paths: kind, arguments, expected path, description.
# "property" walks is_a/ako upwards, "part" follows part_of, "room" mixes
# part_of / stands_on / located_in.
PATHS = [
    (
        "property", ("sofa_1", "soft"),
        ["sofa_1", "sofa"],
        "The property soft is stored one step up, on the class sofa.",
    ),
    (
        "property", ("sofa_1", "movable"),
        ["sofa_1", "sofa", "seating", "furniture"],
        "Three steps up: the sofa is seating, seating is furniture, "
        "furniture is movable.",
    ),
    (
        "property", ("lamp_1", "occupies_space"),
        ["lamp_1", "lamp", "appliance", "thing"],
        "All the way to the root of the network.",
    ),
    (
        "part", ("cushion_cover_1", "sofa_1"),
        ["cushion_cover_1", "cushion_1", "sofa_1"],
        "Two PART-OF links chained by the transitive rule.",
    ),
    (
        "room", ("lamp_1", "living_room_1"),
        ["lamp_1", "coffee_table_1", "living_room_1"],
        "stands_on then located_in: the lamp inherits the room from the table.",
    ),
    (
        "room", ("cushion_cover_1", "living_room_1"),
        ["cushion_cover_1", "cushion_1", "sofa_1", "living_room_1"],
        "The longest chain in the network: part_of, part_of, located_in.",
    ),
]

# The example from the lab methodology, used to show the engine behaves like
# real Prolog rather than being tailored to the furniture knowledge base.
METHODOLOGY_EXAMPLE = """
ako(student, person).
ako(blogger, person).

is_a(olena, blogger).
is_a(andrii, student).
is_a(post1, text_post).
ako(text_post, post).

friend_of(olena, andrii).
posted(olena, post1).
liked(andrii, post1).

has_property(person, can_think).
has_property(student, looking_for_job).

subclass_of(X, Y) :- is_a(X, Y).
subclass_of(X, Y) :- is_a(X, Z), subclass_of(Z, Y).
subclass_of(X, Y) :- ako(X, Y).
subclass_of(X, Y) :- ako(X, Z), subclass_of(Z, Y).

inherited_property(X, P) :- has_property(X, P).
inherited_property(X, P) :- subclass_of(X, Class), has_property(Class, P).
"""


# ------------------------------------------------------------------
# Path reconstruction: one step of the network per query, mirroring the
# clause order of demo.pl so both runners report the same path.
# ------------------------------------------------------------------

def step_targets(kb: KnowledgeBase, relation: str, node: str) -> list[str]:
    return [str(binding["T"]) for binding in kb.query(f"{relation}({node}, T)")]


def property_path(kb: KnowledgeBase, node: str, prop: str) -> list[str] | None:
    """Path from a node up to the class that actually stores the property."""
    if kb.holds(f"has_property({node}, {prop})"):
        return [node]
    for relation in ("is_a", "ako"):                 # same order as up_link/2
        for parent in step_targets(kb, relation, node):
            rest = property_path(kb, parent, prop)
            if rest is not None:
                return [node] + rest
    return None


def part_path(kb: KnowledgeBase, node: str, target: str) -> list[str] | None:
    if node == target:
        return [node]
    for whole in step_targets(kb, "part_of", node):
        rest = part_path(kb, whole, target)
        if rest is not None:
            return [node] + rest
    return None


def room_path(kb: KnowledgeBase, node: str, room: str) -> list[str] | None:
    if kb.holds(f"located_in({node}, {room})"):
        return [node, room]
    for relation in ("part_of", "stands_on"):        # same order as room_step/2
        for support in step_targets(kb, relation, node):
            rest = room_path(kb, support, room)
            if rest is not None:
                return [node] + rest
    return None


PATH_BUILDERS = {
    "property": property_path,
    "part": part_path,
    "room": room_path,
}


# ------------------------------------------------------------------
# Runners
# ------------------------------------------------------------------

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


def run_paths(kb: KnowledgeBase) -> bool:
    print("Derivation paths (lab step 9):")
    all_passed = True
    for kind, args, expected, description in PATHS:
        actual = PATH_BUILDERS[kind](kb, *args)
        passed = actual == expected
        all_passed &= passed
        label = f"{kind}_path({args[0]}, {args[1]})"
        print(f"   {label}")
        print(f"      path: {' -> '.join(actual) if actual else 'none'}")
        print(f"      {description}")
        print(f"      [{'ok' if passed else 'MISMATCH'}]")
    print()
    return all_passed


def run_node_summary(kb: KnowledgeBase) -> bool:
    """The lab requires properties for at least 20 nodes."""
    nodes: set[str] = set()
    for goal, key in (
        ("ako(N, _)", "N"), ("ako(_, N)", "N"), ("is_a(N, _)", "N"),
        ("part_of(N, _)", "N"), ("has_property(N, _)", "N"),
    ):
        nodes.update(str(binding[key]) for binding in kb.query(goal))

    with_properties = {}
    for node in sorted(nodes):
        props = sorted({str(b["P"]) for b in kb.query(f"inherited_property({node}, P)")})
        if props:
            with_properties[node] = props

    print("Nodes carrying at least one property (own or inherited):")
    for node, props in with_properties.items():
        print(f"   {node} ({len(props)}): {props}")

    passed = len(with_properties) >= 20
    print(f"   [{'ok' if passed else 'MISMATCH'}] {len(with_properties)} of "
          f"{len(nodes)} nodes have properties, at least 20 required")
    print()
    return passed


def run_engine_self_test() -> bool:
    print("Engine self-test on the example from the lab methodology:")
    kb = KnowledgeBase.from_text(METHODOLOGY_EXAMPLE)
    olena_is_person = kb.holds("subclass_of(olena, person)")
    olena_thinks = kb.holds("inherited_property(olena, can_think)")
    andrii_job = kb.holds("inherited_property(andrii, looking_for_job)")
    olena_job = kb.holds("inherited_property(olena, looking_for_job)")
    passed = olena_is_person and olena_thinks and andrii_job and not olena_job
    print(f"   ?- subclass_of(olena, person).  ->  {str(olena_is_person).lower()}")
    print(f"   ?- inherited_property(olena, can_think).  ->  {str(olena_thinks).lower()}")
    print(f"   ?- inherited_property(andrii, looking_for_job).  ->  {str(andrii_job).lower()}")
    print(f"   ?- inherited_property(olena, looking_for_job).  ->  {str(olena_job).lower()}")
    print(f"   [{'ok' if passed else 'MISMATCH'}] olena reaches person through "
          f"blogger, but only students look for a job")
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
        run_paths(kb),
        run_node_summary(kb),
        run_engine_self_test(),
    ]

    print("=" * 70)
    print("ALL CHECKS PASSED" if all(results) else "SOME CHECKS FAILED")


if __name__ == "__main__":
    main()
