"""Tkinter UI for the 15-puzzle. Talks to solver.py only through its
public functions and never touches search internals directly."""

from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from tkinter import ttk

import solver

TILE_PX = 90
GAP_PX = 6
STEP_DELAY_MS = 15
STEPS_PER_MOVE = 6


class PuzzleApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Fifteen Puzzle")
        self.state: solver.State = solver.GOAL
        self.user_moves = 0
        self.busy = False

        self._build_widgets()
        self.render()

    def _build_widgets(self) -> None:
        board_px = 4 * TILE_PX + 3 * GAP_PX
        self.canvas = tk.Canvas(self.root, width=board_px, height=board_px, bg="#c7bda3", highlightthickness=0)
        self.canvas.grid(row=0, column=0, columnspan=2, padx=12, pady=12)
        self.canvas.bind("<Button-1>", self._on_click)

        self.tile_rects: dict[int, int] = {}
        self.tile_labels: dict[int, int] = {}
        for value in range(1, 16):
            rect = self.canvas.create_rectangle(0, 0, TILE_PX, TILE_PX, fill="#fbf8f0", outline="#d8cfb8", width=2)
            label = self.canvas.create_text(0, 0, text=str(value), font=("Consolas", 22, "bold"), fill="#2b2320")
            self.tile_rects[value] = rect
            self.tile_labels[value] = label

        self.status_var = tk.StringVar()
        ttk.Label(self.root, textvariable=self.status_var, font=("Consolas", 11, "bold")).grid(
            row=1, column=0, columnspan=2, sticky="w", padx=12
        )

        self.shuffle_btn = ttk.Button(self.root, text="Shuffle", command=self.on_shuffle)
        self.shuffle_btn.grid(row=2, column=0, padx=12, pady=8, sticky="ew")
        self.solve_btn = ttk.Button(self.root, text="Solve with A*", command=self.on_solve)
        self.solve_btn.grid(row=2, column=1, padx=12, pady=8, sticky="ew")

        self.stats_var = tk.StringVar(value="")
        ttk.Label(self.root, textvariable=self.stats_var, font=("Consolas", 10), justify="left").grid(
            row=3, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 12)
        )

        self._build_math_panel()

    def _build_math_panel(self) -> None:
        panel = ttk.LabelFrame(self.root, text="Current state")
        panel.grid(row=0, column=2, rowspan=4, padx=(0, 12), pady=12, sticky="n")

        self.manhattan_var = tk.StringVar(value="0")
        self.conflicts_var = tk.StringVar(value="0")
        self.heuristic_var = tk.StringVar(value="0")
        self.inversions_var = tk.StringVar(value="0")

        rows = [
            ("Manhattan distance", self.manhattan_var),
            ("Linear conflicts", self.conflicts_var),
            ("Heuristic h(n)", self.heuristic_var),
            ("Inversions", self.inversions_var),
        ]
        for row, (label_text, var) in enumerate(rows):
            ttk.Label(panel, text=label_text, font=("Consolas", 9)).grid(
                row=row, column=0, sticky="w", padx=(10, 16), pady=5
            )
            ttk.Label(panel, textvariable=var, font=("Consolas", 11, "bold")).grid(
                row=row, column=1, sticky="e", padx=(0, 10), pady=5
            )

        ttk.Label(
            panel,
            text="h(n) = Manhattan\n      + 2 × conflicts",
            font=("Consolas", 8),
            foreground="#66707f",
            justify="left",
        ).grid(row=len(rows), column=0, columnspan=2, sticky="w", padx=10, pady=(10, 10))

    # --- rendering -----------------------------------------------------

    def _tile_xy(self, index: int) -> tuple[float, float]:
        row, col = divmod(index, 4)
        return col * (TILE_PX + GAP_PX), row * (TILE_PX + GAP_PX)

    def _place(self, value: int, index: int) -> None:
        x, y = self._tile_xy(index)
        self.canvas.coords(self.tile_rects[value], x, y, x + TILE_PX, y + TILE_PX)
        self.canvas.coords(self.tile_labels[value], x + TILE_PX / 2, y + TILE_PX / 2)

    def render(self) -> None:
        for index, value in enumerate(self.state):
            if value != 0:
                self._place(value, index)
        self._refresh_info()

    def _refresh_info(self) -> None:
        self._update_status()
        self._update_math()

    def _update_status(self) -> None:
        if self.state == solver.GOAL:
            self.status_var.set("● Solved")
        elif solver.is_solvable(self.state):
            self.status_var.set("● Solvable")
        else:
            self.status_var.set("● Unsolvable")

    def _update_math(self) -> None:
        breakdown = solver.heuristic_breakdown(self.state)
        self.manhattan_var.set(str(breakdown.manhattan))
        self.conflicts_var.set(str(breakdown.conflicts))
        self.heuristic_var.set(str(breakdown.total))

        inversions = solver.count_inversions(self.state)
        parity = "even" if inversions % 2 == 0 else "odd"
        self.inversions_var.set(f"{inversions} ({parity})")

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.shuffle_btn.configure(state=state)
        self.solve_btn.configure(state=state)

    # --- animation -------------------------------------------------------

    def _slide_tile(self, value: int, from_index: int, to_index: int, step: int, on_done) -> None:
        x0, y0 = self._tile_xy(from_index)
        x1, y1 = self._tile_xy(to_index)
        t = step / STEPS_PER_MOVE
        x, y = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
        self.canvas.coords(self.tile_rects[value], x, y, x + TILE_PX, y + TILE_PX)
        self.canvas.coords(self.tile_labels[value], x + TILE_PX / 2, y + TILE_PX / 2)
        if step < STEPS_PER_MOVE:
            self.root.after(STEP_DELAY_MS, self._slide_tile, value, from_index, to_index, step + 1, on_done)
        else:
            on_done()

    def _apply_move(self, next_state: solver.State, on_done) -> None:
        blank_before = self.state.index(0)
        moved_value = next_state[blank_before]
        from_index = self.state.index(moved_value)
        self.state = next_state
        self._refresh_info()  # numbers update the instant the move is logically made
        self._slide_tile(moved_value, from_index, blank_before, 0, on_done)

    # --- interaction -----------------------------------------------------

    def _on_click(self, event: tk.Event) -> None:
        if self.busy:
            return
        col, row = event.x // (TILE_PX + GAP_PX), event.y // (TILE_PX + GAP_PX)
        if not (0 <= row < 4 and 0 <= col < 4):
            return
        index = row * 4 + col
        value = self.state[index]
        if value == 0:
            return
        blank_row, blank_col = divmod(self.state.index(0), 4)
        if abs(row - blank_row) + abs(col - blank_col) != 1:
            return

        next_state = list(self.state)
        blank = self.state.index(0)
        next_state[blank], next_state[index] = next_state[index], next_state[blank]

        self._set_busy(True)
        self._apply_move(tuple(next_state), on_done=self._finish_manual_move)

    def _finish_manual_move(self) -> None:
        self.user_moves += 1
        self._set_busy(False)

    def on_shuffle(self) -> None:
        if self.busy:
            return
        self.state = solver.random_shuffle(60)
        self.user_moves = 0
        self.stats_var.set("")
        self.render()

    def on_solve(self) -> None:
        # A* on a hard instance can take several seconds in pure Python, so
        # the search runs on a worker thread and hands its result back
        # through a queue -- otherwise it would block Tkinter's single UI
        # thread and the window would appear frozen for that whole time.
        if self.busy or not solver.is_solvable(self.state):
            return
        self._set_busy(True)
        self.status_var.set("● Solving…")
        self.stats_var.set("")

        result_queue: queue.Queue = queue.Queue()
        start_state = self.state

        def worker() -> None:
            started = time.perf_counter()
            result = solver.solve(start_state)
            elapsed_ms = (time.perf_counter() - started) * 1000
            result_queue.put((result, elapsed_ms))

        threading.Thread(target=worker, daemon=True).start()
        self._poll_solve(result_queue)

    def _poll_solve(self, result_queue: "queue.Queue") -> None:
        try:
            result, elapsed_ms = result_queue.get_nowait()
        except queue.Empty:
            self.root.after(50, self._poll_solve, result_queue)
            return

        if result is None:
            self._set_busy(False)
            return

        self.stats_var.set(
            f"solution length: {len(result.path) - 1}\n"
            f"states visited:  {result.nodes_expanded}\n"
            f"search time:     {elapsed_ms:.1f} ms"
        )
        self._animate_solution(result.path, 1)

    def _animate_solution(self, path: list[solver.State], index: int) -> None:
        if index >= len(path):
            self._set_busy(False)
            return
        self._apply_move(path[index], on_done=lambda: self._animate_solution(path, index + 1))


def main() -> None:
    root = tk.Tk()
    PuzzleApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
