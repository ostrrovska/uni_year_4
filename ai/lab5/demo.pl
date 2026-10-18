% ============================================================
% demo.pl - runs every query against the semantic network and
% checks the answers, then prints the derivation path for each
% inherited property (lab step 9).
%
% Usage:   swipl demo.pl
% ============================================================

:- consult(knowledge_base).
:- initialization(main, main).


% ------------------------------------------------------------
% Queries with variables: Label, Template, Goal, Description, Expected
% ------------------------------------------------------------

demo_query('inherited_property(sofa_1, X)', X, inherited_property(sofa_1, X),
    'Everything the sofa knows about itself: only three_seater is its own.',
    [for_sitting, has_price, has_seat, movable, occupies_space,
     seats_several, soft, three_seater]).

demo_query('furniture_in(living_room_1, X)', X, furniture_in(living_room_1, X),
    'Furniture in the living room: tv_1 and lamp_1 are appliances, so excluded.',
    [armchair_1, chair_2, chest_of_drawers_1, coffee_table_1,
     dining_table_1, sofa_1]).

demo_query('component_of(cushion_cover_1, X)', X, component_of(cushion_cover_1, X),
    'Transitive PART-OF: the cover belongs to the cushion and to the sofa.',
    [cushion_1, sofa_1]).

demo_query('in_room(lamp_1, X)', X, in_room(lamp_1, X),
    'The lamp has no located_in fact: its room comes through stands_on.',
    [living_room_1]).

demo_query('soft_furniture(X)', X, soft_furniture(X),
    'Classes and objects alike inherit the property soft.',
    [armchair, armchair_1, sofa, sofa_1]).

demo_query('needs_power(X)', X, needs_power(X),
    'Inherited from the class appliance, stored on no single object.',
    [appliance, lamp, lamp_1, tv, tv_1]).

demo_query('subclass_of(X, storage)', X, subclass_of(X, storage),
    'Everything below storage, both subclasses and instances.',
    [bookshelf, bookshelf_1, chest_of_drawers, chest_of_drawers_1,
     wardrobe, wardrobe_1]).

demo_query('made_of(X, wood)', X, made_of(X, wood),
    'Domain relation 2: a plain fact lookup, no inference involved.',
    [bed_1, bookshelf_1, chair_1, chest_of_drawers_1, desk_1,
     dining_table_1, wardrobe_1]).

demo_query('in_room(X, study_1)', X, in_room(X, study_1),
    'The study also contains the drawer and the shelf, through PART-OF.',
    [bookshelf_1, chair_1, desk_1, drawer_1, shelf_1]).

demo_query('easy_to_move(X)', X, easy_to_move(X),
    'Negation as failure: movable but not inherited as heavy, so the bed and the wardrobe drop out.',
    [armchair, armchair_1, bookshelf, bookshelf_1, chair, chair_1, chair_2,
     chest_of_drawers, chest_of_drawers_1, coffee_table, coffee_table_1,
     desk, desk_1, dining_table, dining_table_1, furniture, seating, sofa,
     sofa_1, storage, table]).


% ------------------------------------------------------------
% Ground goals: Label, Goal, Expected, Comment
% ------------------------------------------------------------

demo_check('subclass_of(sofa_1, furniture)', subclass_of(sofa_1, furniture), true,
    'Two steps up the hierarchy, stored nowhere as a fact.').
demo_check('inherited_property(sofa_1, movable)', inherited_property(sofa_1, movable), true,
    'The property sits on furniture; the sofa only inherits it.').
demo_check('easy_to_move(wardrobe_1)', easy_to_move(wardrobe_1), false,
    'The wardrobe inherits heavy, so negation as failure rejects it.').
demo_check('soft_furniture(desk_1)', soft_furniture(desk_1), false,
    'No class above the desk carries the property soft.').
demo_check('in_room(cushion_cover_1, living_room_1)', in_room(cushion_cover_1, living_room_1), true,
    'Three links: part_of, part_of, located_in.').


% ------------------------------------------------------------
% Derivation paths (lab step 9: show how each answer was reached).
% up_link/2 is the single step upwards; the rest is a plain walk.
% ------------------------------------------------------------

up_link(X, Y) :- is_a(X, Y).
up_link(X, Y) :- ako(X, Y).

hierarchy_path(X, X, [X]).
hierarchy_path(X, Y, [X | Rest]) :-
    up_link(X, Z),
    hierarchy_path(Z, Y, Rest).

% Path from a node up to the class that actually stores the property.
property_path(Node, Property, Path) :-
    hierarchy_path(Node, Source, Path),
    has_property(Source, Property).

% Path along PART-OF links.
part_path(X, X, [X]).
part_path(X, Y, [X | Rest]) :-
    part_of(X, Z),
    part_path(Z, Y, Rest).

% Path from an object to the room containing it, through whatever
% combination of part_of / stands_on / located_in applies.
room_step(X, Y) :- part_of(X, Y).
room_step(X, Y) :- stands_on(X, Y).

room_path(X, Room, [X, Room]) :-
    located_in(X, Room).
room_path(X, Room, [X | Rest]) :-
    room_step(X, Z),
    room_path(Z, Room, Rest).


% Label, Goal producing Path, ExpectedPath, Description
demo_path('inherited_property(sofa_1, soft)',
    property_path(sofa_1, soft, P), P,
    [sofa_1, sofa],
    'The property soft is stored one step up, on the class sofa.').

demo_path('inherited_property(sofa_1, movable)',
    property_path(sofa_1, movable, P), P,
    [sofa_1, sofa, seating, furniture],
    'Three steps up: the sofa is seating, seating is furniture, furniture is movable.').

demo_path('inherited_property(lamp_1, occupies_space)',
    property_path(lamp_1, occupies_space, P), P,
    [lamp_1, lamp, appliance, thing],
    'All the way to the root of the network.').

demo_path('component_of(cushion_cover_1, sofa_1)',
    part_path(cushion_cover_1, sofa_1, P), P,
    [cushion_cover_1, cushion_1, sofa_1],
    'Two PART-OF links chained by the transitive rule.').

demo_path('in_room(lamp_1, living_room_1)',
    room_path(lamp_1, living_room_1, P), P,
    [lamp_1, coffee_table_1, living_room_1],
    'stands_on then located_in: the lamp inherits the room from the table.').

demo_path('in_room(cushion_cover_1, living_room_1)',
    room_path(cushion_cover_1, living_room_1, P), P,
    [cushion_cover_1, cushion_1, sofa_1, living_room_1],
    'The longest chain in the network: part_of, part_of, located_in.').


% ------------------------------------------------------------
% Runner
% ------------------------------------------------------------

write_path([]).
write_path([X]) :- !, format("~w", [X]).
write_path([X | Rest]) :-
    format("~w -> ", [X]),
    write_path(Rest).

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

run_path(Status) :-
    demo_path(Label, Goal, Path, Expected, Description),
    (   call(Goal) ->  Actual = Path ;  Actual = none ),
    (   Actual == Expected
    ->  Status = ok, Mark = ok
    ;   Status = failed, Mark = 'MISMATCH'
    ),
    format("   ~w~n", [Label]),
    format("      path: "), write_path(Actual), nl,
    format("      ~w~n", [Description]),
    format("      [~w]~n", [Mark]).


% ------------------------------------------------------------
% Node summary: the lab requires properties for at least 20 nodes.
% Counts every node that has at least one property, own or inherited.
% ------------------------------------------------------------

network_node(N) :- ako(N, _).
network_node(N) :- ako(_, N).
network_node(N) :- is_a(N, _).
network_node(N) :- part_of(N, _).
network_node(N) :- has_property(N, _).

run_node_summary(Status) :-
    findall(N, network_node(N), Raw),
    sort(Raw, Nodes),
    length(Nodes, Total),
    findall(N, (member(N, Nodes), inherited_property(N, _)), WithRaw),
    sort(WithRaw, WithProps),
    length(WithProps, Count),
    format("Nodes carrying at least one property (own or inherited):~n"),
    forall(member(N, WithProps),
           (   findall(P, inherited_property(N, P), Ps0),
               sort(Ps0, Ps),
               length(Ps, PN),
               format("   ~w (~d): ~w~n", [N, PN, Ps])
           )),
    (   Count >= 20
    ->  Status = ok, Mark = ok
    ;   Status = failed, Mark = 'MISMATCH'
    ),
    format("   [~w] ~d of ~d nodes have properties, at least 20 required~n~n",
           [Mark, Count, Total]).


main :-
    format("~nKnowledge base: knowledge_base.pl (SWI-Prolog ~a)~n", ['10.x']),
    format("======================================================================~n~n"),
    findall(S, run_query(S), QueryStatuses),
    format("Ground goals (true/false):~n"),
    findall(S, run_check(S), CheckStatuses),
    format("~nDerivation paths (lab step 9):~n"),
    findall(S, run_path(S), PathStatuses),
    nl,
    run_node_summary(SummaryStatus),
    append(QueryStatuses, CheckStatuses, All0),
    append(All0, PathStatuses, All1),
    append(All1, [SummaryStatus], All),
    length(QueryStatuses, NQ),
    length(CheckStatuses, NC),
    length(PathStatuses, NP),
    format("======================================================================~n"),
    % Guards against a clause being silently dropped by a syntax error:
    % without them a missing query would still report success.
    (   NQ =:= 10 -> true
    ;   format("ERROR: expected 10 queries, loaded ~d~n", [NQ]), fail
    ),
    (   NC =:= 5 -> true
    ;   format("ERROR: expected 5 ground goals, loaded ~d~n", [NC]), fail
    ),
    (   NP =:= 6 -> true
    ;   format("ERROR: expected 6 derivation paths, loaded ~d~n", [NP]), fail
    ),
    (   memberchk(failed, All)
    ->  format("SOME CHECKS FAILED~n")
    ;   length(All, Total),
        format("ALL ~d CHECKS PASSED (~d queries + ~d ground goals + ~d paths + 1 summary)~n",
               [Total, NQ, NC, NP])
    ).
