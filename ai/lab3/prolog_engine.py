"""A miniature Prolog interpreter: tokenizer, parser, unification and SLD
resolution. Knows nothing about chemistry -- it loads and runs any knowledge
base written in the supported subset of Prolog syntax.

Supported subset: facts, rules with conjunctive bodies, atoms, integers,
variables, nested compound terms, negation as failure (\\+), and the infix
builtins = and \\=. No lists, arithmetic, cut or I/O."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator


# ------------------------------------------------------------------
# Terms
# ------------------------------------------------------------------

@dataclass(frozen=True)
class Atom:
    name: str

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True)
class Var:
    name: str

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True)
class Struct:
    functor: str
    args: tuple

    def __str__(self) -> str:
        return f"{self.functor}({', '.join(str(a) for a in self.args)})"


Term = Atom | Var | Struct


@dataclass(frozen=True)
class Clause:
    head: Term
    body: tuple[Term, ...]


# ------------------------------------------------------------------
# Tokenizer
# ------------------------------------------------------------------

_SYMBOLS = [":-", "\\=", "\\+", "(", ")", ",", ".", "="]


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "%":                                  # comment to end of line
            while i < len(text) and text[i] != "\n":
                i += 1
            continue
        if ch.isspace():
            i += 1
            continue
        if ch.isalnum() or ch == "_":                  # name or number
            start = i
            while i < len(text) and (text[i].isalnum() or text[i] == "_"):
                i += 1
            tokens.append(text[start:i])
            continue
        for symbol in _SYMBOLS:                        # longest match first
            if text.startswith(symbol, i):
                tokens.append(symbol)
                i += len(symbol)
                break
        else:
            raise SyntaxError(f"unexpected character {ch!r} at position {i}")
    return tokens


# ------------------------------------------------------------------
# Parser (recursive descent)
# ------------------------------------------------------------------

class Parser:
    def __init__(self, tokens: list[str]) -> None:
        self.tokens = tokens
        self.pos = 0
        self.anonymous_count = 0

    def peek(self) -> str | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def next(self) -> str:
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def expect(self, token: str) -> None:
        actual = self.next()
        if actual != token:
            raise SyntaxError(f"expected {token!r}, got {actual!r}")

    def parse_clauses(self) -> list[Clause]:
        clauses = []
        while self.peek() is not None:
            clauses.append(self.parse_clause())
        return clauses

    def parse_clause(self) -> Clause:
        head = self.parse_term()
        if self.peek() == ":-":
            self.next()
            body = self.parse_body()
        else:
            body = ()
        self.expect(".")
        return Clause(head=head, body=body)

    def parse_body(self) -> tuple[Term, ...]:
        goals = [self.parse_goal()]
        while self.peek() == ",":
            self.next()
            goals.append(self.parse_goal())
        return tuple(goals)

    def parse_goal(self) -> Term:
        if self.peek() == "\\+":                       # negation as failure
            self.next()
            return Struct("\\+", (self.parse_goal(),))
        left = self.parse_term()
        if self.peek() in ("=", "\\="):                # infix builtins
            operator = self.next()
            return Struct(operator, (left, self.parse_term()))
        return left

    def parse_term(self) -> Term:
        token = self.next()
        if not (token[0].isalnum() or token[0] == "_"):
            raise SyntaxError(f"unexpected token {token!r}")
        if token == "_":
            # every occurrence of _ is its own distinct variable
            self.anonymous_count += 1
            return Var(f"_anon{self.anonymous_count}")
        if token[0].isupper() or token[0] == "_":
            return Var(token)
        if self.peek() == "(":                         # compound term
            self.next()
            args = [self.parse_goal()]
            while self.peek() == ",":
                self.next()
                args.append(self.parse_goal())
            self.expect(")")
            return Struct(token, tuple(args))
        return Atom(token)


def parse_program(text: str) -> list[Clause]:
    return Parser(tokenize(text)).parse_clauses()


def parse_goal_text(text: str) -> Term:
    text = text.strip().removeprefix("?-").strip().rstrip(".")
    parser = Parser(tokenize(text))
    goal = parser.parse_goal()
    if parser.peek() is not None:
        raise SyntaxError("trailing input after goal")
    return goal


# ------------------------------------------------------------------
# Unification
# ------------------------------------------------------------------

Substitution = dict[str, Term]


def walk(term: Term, subst: Substitution) -> Term:
    """Follow variable bindings until an unbound variable or concrete term."""
    while isinstance(term, Var) and term.name in subst:
        term = subst[term.name]
    return term


def unify(a: Term, b: Term, subst: Substitution) -> Substitution | None:
    a, b = walk(a, subst), walk(b, subst)
    if a == b:
        return subst
    if isinstance(a, Var):
        return {**subst, a.name: b}
    if isinstance(b, Var):
        return {**subst, b.name: a}
    if isinstance(a, Struct) and isinstance(b, Struct):
        if a.functor != b.functor or len(a.args) != len(b.args):
            return None
        for x, y in zip(a.args, b.args):
            result = unify(x, y, subst)
            if result is None:
                return None
            subst = result
        return subst
    return None


def resolve(term: Term, subst: Substitution) -> Term:
    """Fully instantiate a term, replacing bound variables all the way down."""
    term = walk(term, subst)
    if isinstance(term, Struct):
        return Struct(term.functor, tuple(resolve(a, subst) for a in term.args))
    return term


def collect_vars(term: Term, found: list[str] | None = None) -> list[str]:
    found = [] if found is None else found
    if isinstance(term, Var):
        if term.name not in found and not term.name.startswith("_"):
            found.append(term.name)
    elif isinstance(term, Struct):
        for arg in term.args:
            collect_vars(arg, found)
    return found


def rename(term: Term, mapping: dict[str, Var], suffix: int) -> Term:
    """Give a clause its own fresh variables, so that X in one clause is
    unrelated to X in another."""
    if isinstance(term, Var):
        if term.name not in mapping:
            mapping[term.name] = Var(f"{term.name}#{suffix}")
        return mapping[term.name]
    if isinstance(term, Struct):
        return Struct(term.functor, tuple(rename(a, mapping, suffix) for a in term.args))
    return term


# ------------------------------------------------------------------
# Knowledge base and SLD resolution
# ------------------------------------------------------------------

class KnowledgeBase:
    def __init__(self, clauses: list[Clause]) -> None:
        self.clauses = clauses
        self._counter = 0

    @classmethod
    def from_file(cls, path: str) -> KnowledgeBase:
        with open(path, encoding="utf-8") as handle:
            return cls(parse_program(handle.read()))

    @classmethod
    def from_text(cls, text: str) -> KnowledgeBase:
        return cls(parse_program(text))

    def solve(self, goals: tuple[Term, ...], subst: Substitution) -> Iterator[Substitution]:
        """Each yielded substitution is one solution; exhausting the generator
        is what performs backtracking."""
        if not goals:
            yield subst
            return

        goal, rest = walk(goals[0], subst), goals[1:]

        if isinstance(goal, Struct) and goal.functor == "\\+" and len(goal.args) == 1:
            if next(self.solve((goal.args[0],), subst), None) is None:
                yield from self.solve(rest, subst)
            return

        if isinstance(goal, Struct) and goal.functor == "=" and len(goal.args) == 2:
            result = unify(goal.args[0], goal.args[1], subst)
            if result is not None:
                yield from self.solve(rest, result)
            return

        if isinstance(goal, Struct) and goal.functor == "\\=" and len(goal.args) == 2:
            if unify(goal.args[0], goal.args[1], subst) is None:
                yield from self.solve(rest, subst)
            return

        for clause in self.clauses:
            self._counter += 1
            mapping: dict[str, Var] = {}
            head = rename(clause.head, mapping, self._counter)
            result = unify(goal, head, subst)
            if result is None:
                continue
            body = tuple(rename(b, mapping, self._counter) for b in clause.body)
            yield from self.solve(body + rest, result)

    def query(self, text: str) -> list[dict[str, Term]]:
        """Run a goal and return one dict of variable bindings per solution.
        A goal with no variables returns [{}] when it succeeds, [] when it
        fails -- Prolog's true/false."""
        goal = parse_goal_text(text)
        names = collect_vars(goal)
        solutions = []
        for subst in self.solve((goal,), {}):
            solutions.append({name: resolve(Var(name), subst) for name in names})
        return solutions

    def holds(self, text: str) -> bool:
        return bool(self.query(text))
