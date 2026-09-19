"""State-space search core for the 15-puzzle: no UI code here at all."""

from __future__ import annotations

import heapq
import itertools
import random
from dataclasses import dataclass

State = tuple[int, ...]

SIZE = 4
GOAL: State = tuple(range(1, 16)) + (0,)

# (row delta, col delta, label of the tile that slides into the blank)
_MOVES = [(-1, 0, "down"), (1, 0, "up"), (0, -1, "right"), (0, 1, "left")]


def neighbors(state: State) -> list[tuple[State, str]]:
    blank = state.index(0)
    row, col = divmod(blank, SIZE)
    result = []
    for dr, dc, move in _MOVES:
        nr, nc = row + dr, col + dc
        if 0 <= nr < SIZE and 0 <= nc < SIZE:
            swap = nr * SIZE + nc
            next_state = list(state)
            next_state[blank], next_state[swap] = next_state[swap], next_state[blank]
            result.append((tuple(next_state), move))
    return result


def count_inversions(state: State) -> int:
    tiles = [v for v in state if v != 0]
    return sum(
        1
        for i in range(len(tiles))
        for j in range(i + 1, len(tiles))
        if tiles[i] > tiles[j]
    )


def is_solvable(state: State) -> bool:
    inversions = count_inversions(state)
    blank_row_from_bottom = SIZE - state.index(0) // SIZE
    if blank_row_from_bottom % 2 == 0:
        return inversions % 2 == 1
    return inversions % 2 == 0


def _line_conflicts(goal_positions: list[int]) -> int:
    """Minimum number of tiles that must leave this line to remove every
    conflict in it, found by repeatedly discarding whichever tile is
    currently involved in the most conflicts."""
    n = len(goal_positions)
    if n < 2:
        return 0
    conflicts_with: list[set[int]] = [set() for _ in range(n)]
    for a in range(n):
        for b in range(a + 1, n):
            if goal_positions[a] > goal_positions[b]:
                conflicts_with[a].add(b)
                conflicts_with[b].add(a)
    removed = 0
    while True:
        worst = max(range(n), key=lambda i: len(conflicts_with[i]))
        if not conflicts_with[worst]:
            break
        removed += 1
        for other in conflicts_with[worst]:
            conflicts_with[other].discard(worst)
        conflicts_with[worst].clear()
    return removed


def _heuristic_components(state: State) -> tuple[int, int]:
    """Returns (manhattan_distance, linear_conflicts) separately, so callers
    that only need the combined score and callers that want to display the
    breakdown share the same computation."""
    manhattan = 0
    for index, value in enumerate(state):
        if value == 0:
            continue
        goal_index = value - 1
        manhattan += abs(index // SIZE - goal_index // SIZE) + abs(index % SIZE - goal_index % SIZE)

    conflicts = 0
    for row in range(SIZE):
        line = []
        for col in range(SIZE):
            value = state[row * SIZE + col]
            if value != 0 and (value - 1) // SIZE == row:
                line.append((value - 1) % SIZE)
        conflicts += _line_conflicts(line)
    for col in range(SIZE):
        line = []
        for row in range(SIZE):
            value = state[row * SIZE + col]
            if value != 0 and (value - 1) % SIZE == col:
                line.append((value - 1) // SIZE)
        conflicts += _line_conflicts(line)

    return manhattan, conflicts


def heuristic(state: State) -> int:
    """Manhattan distance plus the linear-conflict correction. Admissible:
    never overestimates the true number of moves remaining."""
    manhattan, conflicts = _heuristic_components(state)
    return manhattan + 2 * conflicts


@dataclass
class HeuristicBreakdown:
    manhattan: int
    conflicts: int
    total: int


def heuristic_breakdown(state: State) -> HeuristicBreakdown:
    manhattan, conflicts = _heuristic_components(state)
    return HeuristicBreakdown(manhattan=manhattan, conflicts=conflicts, total=manhattan + 2 * conflicts)


@dataclass
class SolveResult:
    path: list[State]
    nodes_expanded: int


def solve(start: State) -> SolveResult | None:
    """A* search, f = g + h, with a min-heap open set and lazy deletion of
    stale heap entries instead of a decrease-key operation."""
    counter = itertools.count()
    open_heap = [(heuristic(start), next(counter), 0, start)]
    g_score = {start: 0}
    came_from: dict[State, State] = {}
    closed: set[State] = set()
    nodes_expanded = 0

    while open_heap:
        _, _, g, current = heapq.heappop(open_heap)
        if current in closed:
            continue
        closed.add(current)
        nodes_expanded += 1

        if current == GOAL:
            path = [current]
            while path[-1] in came_from:
                path.append(came_from[path[-1]])
            path.reverse()
            return SolveResult(path=path, nodes_expanded=nodes_expanded)

        for next_state, _ in neighbors(current):
            if next_state in closed:
                continue
            tentative_g = g + 1
            if tentative_g < g_score.get(next_state, float("inf")):
                g_score[next_state] = tentative_g
                came_from[next_state] = current
                heapq.heappush(
                    open_heap,
                    (tentative_g + heuristic(next_state), next(counter), tentative_g, next_state),
                )

    return None


def random_shuffle(steps: int = 60, rng: random.Random | None = None) -> State:
    """Scramble by taking random legal moves from GOAL, which guarantees a
    solvable result since every operator is reversible."""
    rng = rng or random.Random()
    opposite = {"up": "down", "down": "up", "left": "right", "right": "left"}
    state = GOAL
    last_move: str | None = None
    for _ in range(steps):
        candidates = [(s, m) for s, m in neighbors(state) if m != opposite.get(last_move)]
        state, last_move = rng.choice(candidates)
    return state
