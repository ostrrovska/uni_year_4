% ============================================================
% Lab 3 - Formal logic knowledge representation
% Domain: classification of chemical substances
%
% Runs unchanged in SWI-Prolog:  ?- consult('knowledge_base.pl').
% Also executed by the accompanying mini-interpreter: prolog_engine.py
% ============================================================


% ------------------------------------------------------------
% FACTS
% ------------------------------------------------------------

% --- Simple substances: made of a single chemical element ---
simple_substance(oxygen).
simple_substance(hydrogen).
simple_substance(iron).
simple_substance(copper).
simple_substance(sulfur).

% --- Compound substances: made of two or more elements ---
% (named compound_substance, not compound: compound/1 is a builtin in SWI-Prolog)
compound_substance(water).
compound_substance(carbon_dioxide).
compound_substance(calcium_oxide).
compound_substance(methane).
compound_substance(sulfuric_acid).
compound_substance(hydrochloric_acid).
compound_substance(sodium_hydroxide).
compound_substance(potassium_hydroxide).
compound_substance(copper_hydroxide).
compound_substance(sodium_chloride).
compound_substance(copper_sulfate).
compound_substance(calcium_carbonate).

% --- Elemental composition ---
contains(water, hydrogen).
contains(water, oxygen).
contains(carbon_dioxide, carbon).
contains(carbon_dioxide, oxygen).
contains(calcium_oxide, calcium).
contains(calcium_oxide, oxygen).
contains(methane, carbon).
contains(methane, hydrogen).
contains(sulfuric_acid, hydrogen).
contains(sulfuric_acid, sulfur).
contains(sulfuric_acid, oxygen).
contains(hydrochloric_acid, hydrogen).
contains(hydrochloric_acid, chlorine).
contains(sodium_hydroxide, sodium).
contains(sodium_hydroxide, oxygen).
contains(sodium_hydroxide, hydrogen).
contains(potassium_hydroxide, potassium).
contains(potassium_hydroxide, oxygen).
contains(potassium_hydroxide, hydrogen).
contains(copper_hydroxide, copper).
contains(copper_hydroxide, oxygen).
contains(copper_hydroxide, hydrogen).
contains(sodium_chloride, sodium).
contains(sodium_chloride, chlorine).
contains(copper_sulfate, copper).
contains(copper_sulfate, sulfur).
contains(copper_sulfate, oxygen).
contains(calcium_carbonate, calcium).
contains(calcium_carbonate, carbon).
contains(calcium_carbonate, oxygen).

% --- Number of distinct elements in the formula ---
element_count(water, 2).
element_count(carbon_dioxide, 2).
element_count(calcium_oxide, 2).
element_count(methane, 2).
element_count(sulfuric_acid, 3).
element_count(hydrochloric_acid, 2).
element_count(sodium_hydroxide, 3).
element_count(potassium_hydroxide, 3).
element_count(copper_hydroxide, 3).
element_count(sodium_chloride, 2).
element_count(copper_sulfate, 3).
element_count(calcium_carbonate, 3).

% --- Element classification ---
metal(iron).
metal(copper).
metal(sodium).
metal(potassium).
metal(calcium).

nonmetal(oxygen).
nonmetal(hydrogen).
nonmetal(sulfur).
nonmetal(carbon).
nonmetal(chlorine).

% --- Solubility in water ---
soluble(sulfuric_acid).
soluble(hydrochloric_acid).
soluble(sodium_hydroxide).
soluble(potassium_hydroxide).
soluble(sodium_chloride).
soluble(copper_sulfate).

insoluble(copper_hydroxide).
insoluble(calcium_carbonate).
insoluble(calcium_oxide).

% --- State of matter at room temperature ---
state_of_matter(oxygen, gas).
state_of_matter(hydrogen, gas).
state_of_matter(carbon_dioxide, gas).
state_of_matter(methane, gas).
state_of_matter(water, liquid).
state_of_matter(sulfuric_acid, liquid).
state_of_matter(iron, solid).
state_of_matter(copper, solid).
state_of_matter(sulfur, solid).
state_of_matter(sodium_chloride, solid).
state_of_matter(calcium_carbonate, solid).

% --- Acid residues (anions) ---
acid_residue(sulfuric_acid, sulfate).
acid_residue(hydrochloric_acid, chloride).
acid_residue(sodium_chloride, chloride).
acid_residue(copper_sulfate, sulfate).
acid_residue(calcium_carbonate, carbonate).

% --- Metal cations ---
metal_cation(sodium_hydroxide, sodium).
metal_cation(potassium_hydroxide, potassium).
metal_cation(copper_hydroxide, copper).
metal_cation(sodium_chloride, sodium).
metal_cation(copper_sulfate, copper).
metal_cation(calcium_carbonate, calcium).

% --- Presence of the hydroxyl group OH ---
hydroxyl_group(sodium_hydroxide).
hydroxyl_group(potassium_hydroxide).
hydroxyl_group(copper_hydroxide).


% ------------------------------------------------------------
% RULES
% ------------------------------------------------------------

% Rule 1. An oxide is a two-element compound containing oxygen.
oxide(X) :-
    compound_substance(X),
    contains(X, oxygen),
    element_count(X, 2).

% Rule 2. An acid contains hydrogen and an acid residue.
acid(X) :-
    compound_substance(X),
    contains(X, hydrogen),
    acid_residue(X, _).

% Rule 3. A base consists of a metal cation and a hydroxyl group.
base(X) :-
    compound_substance(X),
    metal_cation(X, _),
    hydroxyl_group(X).

% Rule 4. A salt has a metal cation and an acid residue, but no hydroxyl group.
% Uses negation as failure (\+) to exclude basic hydroxides.
salt(X) :-
    compound_substance(X),
    metal_cation(X, _),
    acid_residue(X, _),
    \+ hydroxyl_group(X).

% Rule 5. An alkali is a water-soluble base.
% Builds on top of rule 3: inference over an already inferred predicate.
alkali(X) :-
    base(X),
    soluble(X).

% Rule 6. An electrolyte dissociates into ions in water.
% Three separate clauses act as a disjunction (idiomatic Prolog).
electrolyte(X) :-
    acid(X),
    soluble(X).
electrolyte(X) :-
    alkali(X).
electrolyte(X) :-
    salt(X),
    soluble(X).

% Rule 7. A compound that does not conduct in solution.
non_electrolyte(X) :-
    compound_substance(X),
    \+ electrolyte(X).

% Rule 8. A neutralization reaction occurs between an acid and a base.
neutralization(Acid, Base) :-
    acid(Acid),
    base(Base).

% Rule 9. General classification predicate over all derived classes.
substance_class(X, oxide) :- oxide(X).
substance_class(X, acid) :- acid(X).
substance_class(X, base) :- base(X).
substance_class(X, salt) :- salt(X).
substance_class(X, simple_substance) :- simple_substance(X).

% Rule 10. Two different substances belonging to the same class.
same_class(X, Y) :-
    substance_class(X, Class),
    substance_class(Y, Class),
    X \= Y.


% ------------------------------------------------------------
% QUERIES (run these in SWI-Prolog after consulting this file)
% ------------------------------------------------------------
%
% ?- substance_class(water, X).
% ?- alkali(X).
% ?- salt(X).
% ?- electrolyte(X).
% ?- non_electrolyte(X).
% ?- neutralization(sulfuric_acid, X).
% ?- oxide(X).
% ?- same_class(sodium_chloride, X).
% ?- acid(water).
