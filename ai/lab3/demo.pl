% ============================================================
% demo.pl - runs every query against the knowledge base and
% checks the answers against what chemistry requires.
%
% Usage:   swipl demo.pl
% ============================================================

:- consult(knowledge_base).
:- initialization(main, main).


% ------------------------------------------------------------
% Queries with variables: Label, Template, Goal, Description, Expected
% ------------------------------------------------------------

demo_query('substance_class(water, X)', X, substance_class(water, X),
    'To which class does water belong?',
    [oxide]).

demo_query('oxide(X)', X, oxide(X),
    'All oxides: two-element compounds containing oxygen.',
    [calcium_oxide, carbon_dioxide, water]).

demo_query('acid(X)', X, acid(X),
    'Water contains hydrogen but has no acid residue, so it is excluded.',
    [hydrochloric_acid, sulfuric_acid]).

demo_query('base(X)', X, base(X),
    'Bases: metal cation plus hydroxyl group.',
    [copper_hydroxide, potassium_hydroxide, sodium_hydroxide]).

demo_query('alkali(X)', X, alkali(X),
    'Alkalis are soluble bases only: copper_hydroxide is insoluble.',
    [potassium_hydroxide, sodium_hydroxide]).

demo_query('salt(X)', X, salt(X),
    'Salts: metal cation and acid residue, no hydroxyl group (negation as failure).',
    [calcium_carbonate, copper_sulfate, sodium_chloride]).

demo_query('electrolyte(X)', X, electrolyte(X),
    'Electrolytes: soluble acids, alkalis and soluble salts.',
    [copper_sulfate, hydrochloric_acid, potassium_hydroxide,
     sodium_chloride, sodium_hydroxide, sulfuric_acid]).

demo_query('non_electrolyte(X)', X, non_electrolyte(X),
    'Derived purely by negation as failure.',
    [calcium_carbonate, calcium_oxide, carbon_dioxide, copper_hydroxide,
     methane, water]).

demo_query('neutralization(sulfuric_acid, X)', X, neutralization(sulfuric_acid, X),
    'Which bases react with sulfuric acid?',
    [copper_hydroxide, potassium_hydroxide, sodium_hydroxide]).

demo_query('same_class(sodium_chloride, X)', X, same_class(sodium_chloride, X),
    'Other substances of the same class as sodium chloride.',
    [calcium_carbonate, copper_sulfate]).


% ------------------------------------------------------------
% Ground goals: Label, Goal, Expected, Comment
% ------------------------------------------------------------

demo_check('acid(water)', acid(water), false,
    'Water is not an acid, even though it contains hydrogen.').
demo_check('oxide(water)', oxide(water), true,
    'Water is hydrogen oxide.').
demo_check('alkali(copper_hydroxide)', alkali(copper_hydroxide), false,
    'A base, but insoluble, so not an alkali.').
demo_check('salt(sodium_hydroxide)', salt(sodium_hydroxide), false,
    'A hydroxyl group excludes it from the salts.').
demo_check('electrolyte(methane)', electrolyte(methane), false,
    'Methane does not dissociate into ions.').


% ------------------------------------------------------------
% Runner
% ------------------------------------------------------------

run_query(Status) :-
    demo_query(Label, Template, Goal, Description, Expected),
    findall(Template, Goal, Raw),
    sort(Raw, Answers),
    format("?- ~w.~n", [Label]),
    format("   ~w~n", [Description]),
    (   Answers == []
    ->  format("   false.~n")
    ;   forall(member(A, Answers), format("   X = ~w~n", [A]))
    ),
    sort(Expected, SortedExpected),
    (   Answers == SortedExpected
    ->  Status = ok, Mark = ok
    ;   Status = failed, Mark = 'MISMATCH'
    ),
    length(Answers, N),
    format("   [~w] ~d solution(s)~n~n", [Mark, N]).

run_check(Status) :-
    demo_check(Label, Goal, Expected, Comment),
    (   call(Goal) ->  Actual = true ;  Actual = false ),
    (   Actual == Expected
    ->  Status = ok, Mark = ok
    ;   Status = failed, Mark = 'MISMATCH'
    ),
    format("   ?- ~w.  ->  ~w   [~w]~n", [Label, Actual, Mark]),
    format("      ~w~n", [Comment]).

main :-
    format("~nKnowledge base: knowledge_base.pl (SWI-Prolog ~a)~n", ['10.x']),
    format("======================================================================~n~n"),
    findall(S, run_query(S), QueryStatuses),
    format("Ground goals (true/false):~n"),
    findall(S, run_check(S), CheckStatuses),
    append(QueryStatuses, CheckStatuses, All),
    format("~n======================================================================~n"),
    length(QueryStatuses, NQ),
    length(CheckStatuses, NC),
    % Guards against a clause being silently dropped by a syntax error:
    % without them a missing query would still report success.
    (   NQ =:= 10 -> true
    ;   format("ERROR: expected 10 queries, loaded ~d~n", [NQ]), fail
    ),
    (   NC =:= 5 -> true
    ;   format("ERROR: expected 5 ground goals, loaded ~d~n", [NC]), fail
    ),
    (   memberchk(failed, All)
    ->  format("SOME CHECKS FAILED~n")
    ;   length(All, Total),
        format("ALL ~d CHECKS PASSED (~d queries + ~d ground goals)~n",
               [Total, NQ, NC])
    ).
