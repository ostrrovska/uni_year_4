# DevOps Lab 2 - intentional failing test to demonstrate a blocked PR. Delete after the demo.


def test_ci_gate_demo_intentional_failure() -> None:
    assert 1 == 2, "intentional failure to show branch protection blocking the merge"
