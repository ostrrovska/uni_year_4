% ============================================================
% Lab 4 - Production model of knowledge representation
% Domain: computer hardware fault diagnosis
%
% Runs unchanged in SWI-Prolog:
%   ?- consult('knowledge_base.pl').
%   ?- what_is_problem.
% ============================================================


% ------------------------------------------------------------
% FACT BASE (dynamic: populated at run time by questions/0)
% ------------------------------------------------------------

:- dynamic condition/1.


% ------------------------------------------------------------
% INPUT PROCEDURE
% Each clause asks one yes/no question and asserts the matching
% condition/1 fact when the answer is "yes". The shared `fail` at
% the end of each clause forces backtracking into the next one, so
% every question gets asked regardless of the previous answer.
% ------------------------------------------------------------

questions :-
    write("Does the computer not start?"), nl,
    read(X), X == yes, assert(condition(computer_not_start)), fail.
questions :-
    write("Is power present?"), nl,
    read(X), X == yes, assert(condition(power_present)), fail.
questions :-
    write("Does the fan not work?"), nl,
    read(X), X == yes, assert(condition(fan_not_work)), fail.
questions :-
    write("Does the monitor not display an image?"), nl,
    read(X), X == yes, assert(condition(monitor_not_work)), fail.
questions :-
    write("Does the computer beep repeatedly on startup?"), nl,
    read(X), X == yes, assert(condition(beep_repeating)), fail.
questions :-
    write("Is there a burning smell from the case?"), nl,
    read(X), X == yes, assert(condition(burning_smell)), fail.
questions.


% ------------------------------------------------------------
% PRODUCTION RULES (antecedent = condition/1 pattern, consequent =
% the diagnosis string). Rules 1-4 are the original diagnostic
% chain; rules 5-6 extend it with two more symptoms.
%
% Rules 2 and 3 are not mutually exclusive: when both fan_not_work
% and monitor_not_work hold, both fire. That is the conflict set
% used in demo.pl to study conflict resolution (control question 8,
% lab steps 10-11).
% ------------------------------------------------------------

action("There is a power supply problem.") :-
    not(condition(power_present)).
action("The power supply unit may be faulty.") :-
    condition(computer_not_start), condition(power_present), condition(fan_not_work).
action("There may be a problem with the video card or monitor.") :-
    condition(computer_not_start), condition(power_present), condition(monitor_not_work).
action("There may be a problem with the motherboard.") :-
    condition(computer_not_start), condition(power_present),
    not(condition(fan_not_work)), not(condition(monitor_not_work)).
action("RAM may be faulty (repeating beep code).") :-
    condition(beep_repeating).
action("Critical fault: burning smell detected, power off immediately.") :-
    condition(burning_smell).


% ------------------------------------------------------------
% INFERENCE ENGINE ENTRY POINT
% Collects answers, takes the first matching rule (Prolog's own
% top-down, clause-order search is the conflict resolution strategy
% in effect here), prints the diagnosis, then clears the fact base
% so the program can be run again from a clean state.
% ------------------------------------------------------------

what_is_problem :-
    questions,
    action(X),
    write(X), nl,
    retractall(condition(_)).
