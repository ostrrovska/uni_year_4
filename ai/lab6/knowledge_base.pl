% ============================================================
% Lab 6 - Frame model of knowledge representation
% Domain: the construction of a house (variant 1, frame-object)
%
% Runs unchanged in SWI-Prolog:  ?- consult('knowledge_base.pl').
% Also executed by the accompanying mini-interpreter: prolog_engine.py
%
% A frame is frame(Name, [Slot-Value, ...]). Two slots are special:
%   ako-Parent  links a concept to the concept above it,
%   isa-Class   links an individual object to its class.
% Everything else is an ordinary slot.
%
% The file deliberately contains no directives, no library calls and no
% write/nl: that is what lets the mini-interpreter load it directly.
% Slot lists are searched with the local slot_in/2 instead of member/2,
% and the demons return a status term instead of printing it. Printing
% is done by demo.pl and queries.py.
% ============================================================


% ------------------------------------------------------------
% CLASS FRAMES - the concept hierarchy, linked by ako
% ------------------------------------------------------------

% --- Root of the hierarchy ---
frame(building_element,
    [ comment-structural_part_of_a_house
    , documented-yes
    ]).

% --- Four large groups of elements ---
frame(structural_element,
    [ ako-building_element
    , load_bearing-yes
    , material-concrete
    ]).

frame(opening,
    [ ako-building_element
    , load_bearing-no
    , can_be_closed-yes
    ]).

frame(room_space,
    [ ako-building_element
    , load_bearing-no
    , has_floor-yes
    , has_ceiling-yes
    ]).

frame(engineering_system,
    [ ako-building_element
    , load_bearing-no
    , needs_service-yes
    ]).

% --- Load-bearing structures ---
frame(foundation,
    [ ako-structural_element
    , material-concrete
    , depth-120
    ]).

frame(wall,
    [ ako-structural_element
    , material-brick
    , thickness-38
    ]).

frame(roof,
    [ ako-structural_element
    , material-metal_tile
    , slope-35
    ]).

frame(floor_slab,
    [ ako-structural_element
    , material-concrete
    , thickness-22
    ]).

% --- Openings ---
frame(window,
    [ ako-opening
    , material-pvc
    , glazing-double
    , width-140
    , height-150
    ]).

frame(door,
    [ ako-opening
    , material-wood
    , width-90
    , height-210
    ]).

% --- Rooms ---
frame(living_room,
    [ ako-room_space
    , purpose-rest
    , area-24
    ]).

frame(kitchen,
    [ ako-room_space
    , purpose-cooking
    , area-14
    ]).

frame(bedroom,
    [ ako-room_space
    , purpose-sleeping
    , area-16
    ]).

frame(bathroom,
    [ ako-room_space
    , purpose-hygiene
    , area-6
    ]).

% --- Engineering systems ---
frame(heating_system,
    [ ako-engineering_system
    , energy-gas
    , season-winter
    ]).

frame(water_supply,
    [ ako-engineering_system
    , energy-none
    ]).

frame(electrical_system,
    [ ako-engineering_system
    , energy-electricity
    ]).

% --- The building as a whole ---
frame(house,
    [ comment-complete_building
    , floors-1
    , roof_type-gable
    ]).

frame(cottage,
    [ ako-house
    , floors-2
    , wall_material-brick
    ]).


% ------------------------------------------------------------
% OBJECT FRAMES - concrete things, linked to their class by isa.
% The part_of slot carries the PART-OF relation between objects.
% ------------------------------------------------------------

frame(house_1,
    [ isa-cottage
    , address-sadova_12
    , area-180
    , year_built-2019
    ]).

frame(foundation_1,
    [ isa-foundation
    , part_of-house_1
    , depth-150
    ]).

frame(wall_a,
    [ isa-wall
    , part_of-house_1
    , side-north
    , thickness-51
    ]).

frame(wall_b,
    [ isa-wall
    , part_of-house_1
    , side-south
    ]).

frame(roof_1,
    [ isa-roof
    , part_of-house_1
    , slope-40
    ]).

frame(floor_slab_1,
    [ isa-floor_slab
    , part_of-house_1
    ]).

frame(window_1,
    [ isa-window
    , part_of-wall_a
    , width-160
    ]).

frame(door_1,
    [ isa-door
    , part_of-wall_b
    ]).

frame(kitchen_1,
    [ isa-kitchen
    , part_of-house_1
    , floor_number-1
    , area-18
    ]).

frame(living_room_1,
    [ isa-living_room
    , part_of-house_1
    , floor_number-1
    ]).

frame(bedroom_1,
    [ isa-bedroom
    , part_of-house_1
    , floor_number-2
    ]).

frame(bathroom_1,
    [ isa-bathroom
    , part_of-house_1
    , floor_number-2
    , area-4
    ]).

frame(heating_1,
    [ isa-heating_system
    , part_of-house_1
    , power-24
    ]).

frame(wiring_1,
    [ isa-electrical_system
    , part_of-house_1
    ]).


% ------------------------------------------------------------
% SLOT ACCESS AND INHERITANCE
% ------------------------------------------------------------

% Rule 1. Membership in a slot list. Defined locally so that the file
% needs no library(lists) and stays loadable by the mini-interpreter.
slot_in(X, [X | _]).
slot_in(X, [_ | Rest]) :- slot_in(X, Rest).

% Rule 2. query/3 reads a slot. The first clause returns the frame's
% own value; the other two inherit, through isa for an object and
% through ako for a class. Because the own clause is tried first, an
% own value is always the first answer and shadows the inherited one.
query(ID, Slot, Value) :-
    frame(ID, Slots),
    slot_in(Slot-Value, Slots).
query(ID, Slot, Value) :-
    frame(ID, Slots),
    slot_in(isa-Class, Slots),
    query(Class, Slot, Value).
query(ID, Slot, Value) :-
    frame(ID, Slots),
    slot_in(ako-Parent, Slots),
    query(Parent, Slot, Value).

% Rule 3. A slot value stored in the frame itself, with no inheritance.
own_slot(ID, Slot, Value) :-
    frame(ID, Slots),
    slot_in(Slot-Value, Slots).

% Rule 4. A value that the frame does not store but reaches by
% inheritance. Useful for showing what inheritance actually adds.
inherited_slot(ID, Slot, Value) :-
    query(ID, Slot, Value),
    \+ own_slot(ID, Slot, Value).

% Rule 5. PART-OF between objects, and its transitive closure.
part_of_frame(Part, Whole) :- query(Part, part_of, Whole).

component_of(Part, Whole) :-
    part_of_frame(Part, Whole).
component_of(Part, Whole) :-
    part_of_frame(Part, Middle),
    component_of(Middle, Whole).

% Rule 6. Class membership: an object belongs to its class and to every
% concept above that class.
instance_of(ID, Class) :-
    frame(ID, Slots),
    slot_in(isa-Class, Slots).
instance_of(ID, Class) :-
    frame(ID, Slots),
    slot_in(isa-Direct, Slots),
    ako_chain(Direct, Class).

ako_chain(Child, Parent) :-
    frame(Child, Slots),
    slot_in(ako-Parent, Slots).
ako_chain(Child, Ancestor) :-
    frame(Child, Slots),
    slot_in(ako-Parent, Slots),
    ako_chain(Parent, Ancestor).


% ------------------------------------------------------------
% DEMON PROCEDURES
% A demon is attached to a slot name and returns a status term:
% ok, warning(Reason) or error(Reason). The clauses of each demon are
% mutually exclusive, so exactly one status comes back and no cut is
% needed (the mini-interpreter does not support cut).
% ------------------------------------------------------------

% Slots that have a demon attached.
has_demon(area).
has_demon(thickness).

% Demon 1 (when-read). Every read of the area slot is validated: the
% value must be a positive number, and a room under 6 square metres is
% reported as suspicious rather than rejected.
demon(area, Value, error(not_a_number)) :-
    \+ number(Value).
demon(area, Value, error(not_positive)) :-
    number(Value),
    \+ Value > 0.
demon(area, Value, warning(too_small)) :-
    number(Value),
    Value > 0,
    Value < 6.
demon(area, Value, ok) :-
    number(Value),
    Value >= 6.

% Demon 2 (when-write). A wall thinner than 25 cm is refused before the
% value is ever stored.
demon(thickness, Value, error(not_a_number)) :-
    \+ number(Value).
demon(thickness, Value, error(too_thin)) :-
    number(Value),
    Value < 25.
demon(thickness, Value, ok) :-
    number(Value),
    Value >= 25.

% Default: a slot with no demon attached is read and written unchecked.
demon(Slot, _, no_demon) :-
    \+ has_demon(Slot).

% Rule 7. Reading a slot fires the when-read demon on the value found.
read_slot(ID, Slot, Value, Status) :-
    query(ID, Slot, Value),
    demon(Slot, Value, Status).

% Rule 8. Writing a slot fires the when-write demon. Nothing is stored:
% the demon only decides whether the write would be allowed.
write_slot(ID, Slot, Value, Status) :-
    frame(ID, _),
    demon(Slot, Value, Status).

% Demon 3 (computing). The category slot is never stored anywhere: it
% is derived from the area slot every time it is asked for.
demon_category(Area, small) :-
    number(Area),
    Area < 100.
demon_category(Area, medium) :-
    number(Area),
    Area >= 100,
    Area < 200.
demon_category(Area, large) :-
    number(Area),
    Area >= 200.

% Rule 9. The computed category of any frame that has an area slot.
category_of(ID, Category) :-
    query(ID, area, Area),
    demon_category(Area, Category).


% ------------------------------------------------------------
% QUERIES (run these in SWI-Prolog after consulting this file)
% ------------------------------------------------------------
%
% ?- query(kitchen_1, area, V).
% ?- query(living_room_1, area, V).
% ?- query(wall_a, comment, V).
% ?- query(window_1, glazing, V).
% ?- query(house_1, floors, V).
% ?- inherited_slot(bedroom_1, purpose, V).
% ?- component_of(window_1, X).
% ?- instance_of(kitchen_1, X).
% ?- read_slot(bathroom_1, area, V, S).
% ?- write_slot(wall_b, thickness, 10, S).
% ?- category_of(house_1, C).
