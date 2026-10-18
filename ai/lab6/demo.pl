% ============================================================
% demo.pl - runs every query against the frame model, shows what is
% an own slot value and what is inherited, and fires the demons on
% correct and on faulty values.
%
% Usage:   swipl demo.pl
% ============================================================

:- consult(knowledge_base).
:- initialization(main, main).


% ------------------------------------------------------------
% Queries with variables: Label, Template, Goal, Description, Expected
%
% The answers are compared in the order Prolog produces them and are
% deliberately NOT sorted: in a frame model the order is the result.
% The frame's own value is always found first and therefore shadows
% the inherited one.
% ------------------------------------------------------------

demo_query('query(kitchen_1, area, V)', V, query(kitchen_1, area, V),
    'Own value 18 comes first and shadows the 14 inherited from the class kitchen.',
    [18, 14]).

demo_query('query(living_room_1, area, V)', V, query(living_room_1, area, V),
    'No own area slot, so the only answer is inherited from the class living_room.',
    [24]).

demo_query('query(wall_a, comment, V)', V, query(wall_a, comment, V),
    'Three steps of inheritance: wall_a isa wall, wall ako structural_element, structural_element ako building_element.',
    [structural_part_of_a_house]).

demo_query('query(window_1, glazing, V)', V, query(window_1, glazing, V),
    'A typical default value taken from the class window.',
    [double]).

demo_query('query(house_1, floors, V)', V, query(house_1, floors, V),
    'Two levels of override: cottage says 2, the more general house says 1.',
    [2, 1]).

demo_query('query(wall_b, material, V)', V, query(wall_b, material, V),
    'The nearest ancestor wins: brick from wall, then concrete from structural_element.',
    [brick, concrete]).

demo_query('query(window_1, width, V)', V, query(window_1, width, V),
    'A wider window than its class default: 160 is its own, 140 is inherited.',
    [160, 140]).

demo_query('inherited_slot(bedroom_1, purpose, V)', V, inherited_slot(bedroom_1, purpose, V),
    'Only values the frame does not store itself.',
    [sleeping]).

demo_query('component_of(window_1, X)', X, component_of(window_1, X),
    'Transitive PART-OF through the part_of slot: the window belongs to the wall and to the house.',
    [wall_a, house_1]).

demo_query('instance_of(kitchen_1, X)', X, instance_of(kitchen_1, X),
    'The class of the object and every concept above it, nearest first.',
    [kitchen, room_space, building_element]).

demo_query('category_of(house_1, C)', C, category_of(house_1, C),
    'Computing demon: the category is derived from area 180, it is stored in no slot.',
    [medium]).


% ------------------------------------------------------------
% Ground goals: Label, Goal, Expected, Comment
% ------------------------------------------------------------

demo_check('query(wall_a, load_bearing, yes)', query(wall_a, load_bearing, yes), true,
    'Inherited two levels up, from structural_element.').
demo_check('query(window_1, glazing, double)', query(window_1, glazing, double), true,
    'The value is reachable...').
demo_check('own_slot(window_1, glazing, double)', own_slot(window_1, glazing, double), false,
    '...but the window frame itself does not store it.').
demo_check('own_slot(house_1, floors, 2)', own_slot(house_1, floors, 2), false,
    'house_1 has no floors slot of its own; the 2 comes from cottage.').
demo_check('component_of(window_1, house_1)', component_of(window_1, house_1), true,
    'Two PART-OF steps chained by the transitive rule.').
demo_check('instance_of(bathroom_1, building_element)', instance_of(bathroom_1, building_element), true,
    'Three steps: bathroom, room_space, building_element.').


% ------------------------------------------------------------
% Demon scenarios: Label, Template, Goal, Description, Expected
% ------------------------------------------------------------

demo_demon('read_slot(kitchen_1, area, V, S)', V-S, read_slot(kitchen_1, area, V, S),
    'when-read demon on a normal kitchen: both the own and the inherited area pass.',
    [18-ok, 14-ok]).

demo_demon('read_slot(bathroom_1, area, V, S)', V-S, read_slot(bathroom_1, area, V, S),
    'The own value 4 is flagged as suspicious, the inherited 6 is accepted.',
    [4-warning(too_small), 6-ok]).

demo_demon('read_slot(bedroom_1, purpose, V, S)', V-S, read_slot(bedroom_1, purpose, V, S),
    'A slot with no demon attached is read unchecked.',
    [sleeping-no_demon]).

demo_demon('read_slot(wall_a, thickness, V, S)', V-S, read_slot(wall_a, thickness, V, S),
    'Both the own 51 and the inherited 38 satisfy the thickness demon.',
    [51-ok, 38-ok]).

demo_demon('write_slot(wall_b, thickness, 10, S)', S, write_slot(wall_b, thickness, 10, S),
    'when-write demon refuses a wall thinner than 25 cm.',
    [error(too_thin)]).

demo_demon('write_slot(wall_b, thickness, 40, S)', S, write_slot(wall_b, thickness, 40, S),
    'The same demon accepts a correct value.',
    [ok]).

demo_demon('write_slot(kitchen_1, area, big, S)', S, write_slot(kitchen_1, area, big, S),
    'A non-numeric value is rejected before it could ever be stored.',
    [error(not_a_number)]).


% ------------------------------------------------------------
% Runner
% ------------------------------------------------------------

run_query(Status) :-
    demo_query(Label, Template, Goal, Description, Expected),
    findall(Template, Goal, Answers),
    format("?- ~w.~n", [Label]),
    format("   ~w~n", [Description]),
    (   Answers == []
    ->  format("   false.~n")
    ;   forall(member(A, Answers), format("   V = ~w~n", [A]))
    ),
    (   Answers == Expected
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

run_demon(Status) :-
    demo_demon(Label, Template, Goal, Description, Expected),
    findall(Template, Goal, Answers),
    (   Answers == Expected
    ->  Status = ok, Mark = ok
    ;   Status = failed, Mark = 'MISMATCH'
    ),
    format("   ?- ~w.~n", [Label]),
    format("      ~w~n", [Description]),
    forall(member(A, Answers), format("      -> ~w~n", [A])),
    format("      [~w]~n", [Mark]).


% ------------------------------------------------------------
% Frame summary: the lab requires properties for at least 20 frames.
% Prints the own and the inherited slots of every frame.
% ------------------------------------------------------------

run_frame_summary(Status) :-
    findall(F, frame(F, _), Frames),
    length(Frames, Count),
    format("Own and inherited slots of every frame:~n"),
    forall(member(F, Frames),
           (   findall(S-V, own_slot(F, S, V), Own),
               findall(S-V, inherited_slot(F, S, V), Inherited),
               length(Own, NO),
               length(Inherited, NI),
               format("   ~w  own ~d: ~w~n", [F, NO, Own]),
               format("      inherited ~d: ~w~n", [NI, Inherited])
           )),
    (   Count >= 20
    ->  Status = ok, Mark = ok
    ;   Status = failed, Mark = 'MISMATCH'
    ),
    format("   [~w] ~d frames described, at least 20 required~n~n", [Mark, Count]).


main :-
    format("~nKnowledge base: knowledge_base.pl (SWI-Prolog ~a)~n", ['10.x']),
    format("======================================================================~n~n"),
    findall(S, run_query(S), QueryStatuses),
    format("Ground goals (true/false):~n"),
    findall(S, run_check(S), CheckStatuses),
    format("~nDemon procedures:~n"),
    findall(S, run_demon(S), DemonStatuses),
    nl,
    run_frame_summary(SummaryStatus),
    append(QueryStatuses, CheckStatuses, All0),
    append(All0, DemonStatuses, All1),
    append(All1, [SummaryStatus], All),
    length(QueryStatuses, NQ),
    length(CheckStatuses, NC),
    length(DemonStatuses, ND),
    format("======================================================================~n"),
    % Guards against a clause being silently dropped by a syntax error:
    % without them a missing query would still report success.
    (   NQ =:= 11 -> true
    ;   format("ERROR: expected 11 queries, loaded ~d~n", [NQ]), fail
    ),
    (   NC =:= 6 -> true
    ;   format("ERROR: expected 6 ground goals, loaded ~d~n", [NC]), fail
    ),
    (   ND =:= 7 -> true
    ;   format("ERROR: expected 7 demon scenarios, loaded ~d~n", [ND]), fail
    ),
    (   memberchk(failed, All)
    ->  format("SOME CHECKS FAILED~n")
    ;   length(All, Total),
        format("ALL ~d CHECKS PASSED (~d queries + ~d ground goals + ~d demon scenarios + 1 summary)~n",
               [Total, NQ, NC, ND])
    ).
