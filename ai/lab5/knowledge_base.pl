% ============================================================
% Lab 5 - Semantic network knowledge representation
% Domain: a room and its furniture (variant 7)
%
% Runs unchanged in SWI-Prolog:  ?- consult('knowledge_base.pl').
% Also executed by the accompanying mini-interpreter: prolog_engine.py
%
% Every link is a binary predicate, i.e. a triple (subject, relation,
% object). Link types used here: AKO, IS-A, PART-OF and three relations
% specific to the domain (located_in, made_of, stands_on).
% ============================================================


% ------------------------------------------------------------
% AKO LINKS (A Kind Of): class -> superclass
% The backbone of the hierarchy. Read ako(chair, seating) as
% "a chair is a kind of seating".
% ------------------------------------------------------------

ako(furniture, thing).
ako(room, thing).
ako(appliance, thing).

ako(seating, furniture).
ako(table, furniture).
ako(storage, furniture).
ako(bed, furniture).

ako(chair, seating).
ako(armchair, seating).
ako(sofa, seating).

ako(dining_table, table).
ako(desk, table).
ako(coffee_table, table).

ako(wardrobe, storage).
ako(bookshelf, storage).
ako(chest_of_drawers, storage).

ako(living_room, room).
ako(bedroom, room).
ako(study, room).

ako(lamp, appliance).
ako(tv, appliance).


% ------------------------------------------------------------
% IS-A LINKS (Is A): individual object -> its class
% These are the concrete things standing in the flat.
% ------------------------------------------------------------

is_a(sofa_1, sofa).
is_a(armchair_1, armchair).
is_a(chair_1, chair).
is_a(chair_2, chair).
is_a(desk_1, desk).
is_a(dining_table_1, dining_table).
is_a(coffee_table_1, coffee_table).
is_a(wardrobe_1, wardrobe).
is_a(bookshelf_1, bookshelf).
is_a(chest_of_drawers_1, chest_of_drawers).
is_a(bed_1, bed).
is_a(lamp_1, lamp).
is_a(tv_1, tv).

is_a(living_room_1, living_room).
is_a(bedroom_1, bedroom).
is_a(study_1, study).


% ------------------------------------------------------------
% PART-OF LINKS: component -> whole
% cushion_cover_1 sits two levels deep, so the transitive closure
% in component_of/2 has something real to walk over.
% ------------------------------------------------------------

part_of(cushion_1, sofa_1).
part_of(cushion_cover_1, cushion_1).
part_of(backrest_1, sofa_1).
part_of(drawer_1, desk_1).
part_of(door_w1, wardrobe_1).
part_of(shelf_1, bookshelf_1).
part_of(mattress_1, bed_1).
part_of(leg_1, coffee_table_1).
part_of(window_1, bedroom_1).


% ------------------------------------------------------------
% DOMAIN-SPECIFIC RELATION 1: located_in(Object, Room)
% Which room a piece of furniture stands in.
% tv_1 is deliberately absent here: its room is derived through
% stands_on/2 instead (see rule 4).
% ------------------------------------------------------------

located_in(sofa_1, living_room_1).
located_in(armchair_1, living_room_1).
located_in(coffee_table_1, living_room_1).
located_in(dining_table_1, living_room_1).
located_in(chair_2, living_room_1).
located_in(chest_of_drawers_1, living_room_1).

located_in(bed_1, bedroom_1).
located_in(wardrobe_1, bedroom_1).

located_in(desk_1, study_1).
located_in(chair_1, study_1).
located_in(bookshelf_1, study_1).


% ------------------------------------------------------------
% DOMAIN-SPECIFIC RELATION 2: made_of(Object, Material)
% ------------------------------------------------------------

made_of(sofa_1, fabric).
made_of(armchair_1, fabric).
made_of(desk_1, wood).
made_of(dining_table_1, wood).
made_of(coffee_table_1, glass).
made_of(wardrobe_1, wood).
made_of(bookshelf_1, wood).
made_of(chest_of_drawers_1, wood).
made_of(bed_1, wood).
made_of(chair_1, wood).
made_of(chair_2, plastic).


% ------------------------------------------------------------
% DOMAIN-SPECIFIC RELATION 3: stands_on(Object, Support)
% ------------------------------------------------------------

stands_on(lamp_1, coffee_table_1).
stands_on(tv_1, chest_of_drawers_1).


% ------------------------------------------------------------
% PROPERTIES OF NODES
% Properties are attached as high in the hierarchy as they are
% true, so individual objects do not repeat them: that is exactly
% what inheritance saves.
% ------------------------------------------------------------

% --- Properties of the root and the top-level classes ---
has_property(thing, occupies_space).
has_property(furniture, movable).
has_property(furniture, has_price).
has_property(room, has_walls).
has_property(room, has_floor).
has_property(appliance, needs_electricity).

% --- Properties of the furniture subclasses ---
has_property(seating, for_sitting).
has_property(seating, has_seat).
has_property(table, has_flat_top).
has_property(storage, holds_items).
has_property(bed, for_sleeping).
has_property(bed, heavy).

% --- Properties of the leaf classes ---
has_property(sofa, soft).
has_property(sofa, seats_several).
has_property(armchair, soft).
has_property(chair, has_backrest).
has_property(desk, for_working).
has_property(coffee_table, low).
has_property(dining_table, seats_several).
has_property(wardrobe, has_doors).
has_property(wardrobe, heavy).
has_property(bookshelf, open_front).
has_property(chest_of_drawers, has_drawers).
has_property(living_room, for_guests).
has_property(bedroom, for_rest).
has_property(study, quiet).
has_property(lamp, gives_light).
has_property(tv, has_screen).

% --- Own properties of individual objects (not inherited) ---
has_property(sofa_1, three_seater).
has_property(bed_1, double).
has_property(desk_1, corner_shaped).


% ------------------------------------------------------------
% INFERENCE RULES
% ------------------------------------------------------------

% Rule 1. Transitive closure of the hierarchy. Four clauses: a node
% reaches a class either directly (is_a / ako) or by walking one step
% up and recursing. This is what lets Prolog answer
% subclass_of(sofa_1, furniture) although no such fact is stored.
subclass_of(X, Y) :- is_a(X, Y).
subclass_of(X, Y) :- is_a(X, Z), subclass_of(Z, Y).
subclass_of(X, Y) :- ako(X, Y).
subclass_of(X, Y) :- ako(X, Z), subclass_of(Z, Y).

% Rule 2. Property inheritance: a node has its own properties plus
% every property of every class above it.
inherited_property(X, P) :- has_property(X, P).
inherited_property(X, P) :- subclass_of(X, Class), has_property(Class, P).

% Rule 3. Transitive PART-OF: a cushion cover is a component of the
% sofa even though only the two single steps are stored.
component_of(Part, Whole) :- part_of(Part, Whole).
component_of(Part, Whole) :- part_of(Part, Middle), component_of(Middle, Whole).

% Rule 4. A room contains an object directly, through the whole it
% is a part of, or through whatever it stands on.
in_room(X, Room) :- located_in(X, Room).
in_room(X, Room) :- part_of(X, Whole), in_room(Whole, Room).
in_room(X, Room) :- stands_on(X, Support), in_room(Support, Room).

% Rule 5. Furniture standing in a given room: combines the domain
% relation with the class hierarchy.
furniture_in(Room, X) :- in_room(X, Room), subclass_of(X, furniture).

% Rule 6. Classification over inherited properties, not over facts.
soft_furniture(X) :- inherited_property(X, soft).
needs_power(X) :- inherited_property(X, needs_electricity).

% Rule 7. Negation as failure: movable, but not inherited as heavy.
easy_to_move(X) :-
    inherited_property(X, movable),
    \+ inherited_property(X, heavy).

% Rule 8. Two different objects standing in the same room.
same_room(X, Y) :-
    in_room(X, Room),
    in_room(Y, Room),
    X \= Y.


% ------------------------------------------------------------
% QUERIES (run these in SWI-Prolog after consulting this file)
% ------------------------------------------------------------
%
% ?- subclass_of(sofa_1, furniture).
% ?- inherited_property(sofa_1, X).
% ?- furniture_in(living_room_1, X).
% ?- component_of(cushion_cover_1, X).
% ?- in_room(lamp_1, X).
% ?- soft_furniture(X).
% ?- needs_power(X).
% ?- easy_to_move(wardrobe_1).
