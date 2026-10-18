% ============================================================
% demo.pl - runs every diagnostic scenario against the production
% rules without interactive input, and studies conflict sets and
% rule-order sensitivity (lab steps 10-11).
%
% Usage:   swipl demo.pl
% ============================================================

:- consult(knowledge_base).
:- initialization(main, main).


% ------------------------------------------------------------
% Scenarios: Label, Conditions (asserted directly, bypassing
% questions/0), ExpectedFirst (what what_is_problem/0 would print),
% ExpectedSet (the full conflict set in clause order), Comment.
% ------------------------------------------------------------

demo_scenario(no_power,
    [computer_not_start],
    "There is a power supply problem.",
    ["There is a power supply problem."],
    'No power present at all: rule 1 alone fires.').

demo_scenario(psu_fault,
    [computer_not_start, power_present, fan_not_work],
    "The power supply unit may be faulty.",
    ["The power supply unit may be faulty."],
    'Power present, fan stopped, monitor fine: rule 2 alone.').

demo_scenario(video_fault,
    [computer_not_start, power_present, monitor_not_work],
    "There may be a problem with the video card or monitor.",
    ["There may be a problem with the video card or monitor."],
    'Power present, fan fine, monitor blank: rule 3 alone.').

demo_scenario(motherboard_fault,
    [computer_not_start, power_present],
    "There may be a problem with the motherboard.",
    ["There may be a problem with the motherboard."],
    'Power present, fan and monitor both fine: rule 4 (double negation).').

demo_scenario(ram_fault,
    [power_present, beep_repeating],
    "RAM may be faulty (repeating beep code).",
    ["RAM may be faulty (repeating beep code)."],
    'Independent symptom: repeating beep code only.').

demo_scenario(critical_fault,
    [power_present, burning_smell],
    "Critical fault: burning smell detected, power off immediately.",
    ["Critical fault: burning smell detected, power off immediately."],
    'Independent symptom: burning smell only.').

demo_scenario(conflict,
    [computer_not_start, power_present, fan_not_work, monitor_not_work],
    "The power supply unit may be faulty.",
    ["The power supply unit may be faulty.",
     "There may be a problem with the video card or monitor."],
    'Conflict set of size 2: rules 2 and 3 both match. Declaration order picks rule 2 first.').

demo_scenario(all_symptoms,
    [computer_not_start, power_present, fan_not_work, monitor_not_work,
     beep_repeating, burning_smell],
    "The power supply unit may be faulty.",
    ["The power supply unit may be faulty.",
     "There may be a problem with the video card or monitor.",
     "RAM may be faulty (repeating beep code).",
     "Critical fault: burning smell detected, power off immediately."],
    'Conflict set of size 4. Plain declaration order surfaces the PSU message first even though the burning-smell rule is safety-critical - a real weakness of order-only resolution (see answers.md, Q8).').


% ------------------------------------------------------------
% Rule-order experiment: the same two conflicting rules (2 and 3),
% declared in the opposite order under a different name, so we can
% compare which one Prolog picks first without touching action/1.
% ------------------------------------------------------------

action_swapped(X) :-
    condition(computer_not_start), condition(power_present), condition(monitor_not_work),
    X = "There may be a problem with the video card or monitor.".
action_swapped(X) :-
    condition(computer_not_start), condition(power_present), condition(fan_not_work),
    X = "The power supply unit may be faulty.".


% ------------------------------------------------------------
% Runner
% ------------------------------------------------------------

run_scenario(Status) :-
    demo_scenario(Label, Conditions, ExpectedFirst, ExpectedSet, Comment),
    retractall(condition(_)),
    forall(member(C, Conditions), assert(condition(C))),
    findall(X, action(X), ActualSet),
    (   ActualSet = [ActualFirst | _]
    ->  true
    ;   ActualFirst = none
    ),
    (   ActualFirst == ExpectedFirst, ActualSet == ExpectedSet
    ->  Status = ok, Mark = ok
    ;   Status = failed, Mark = 'MISMATCH'
    ),
    length(ActualSet, N),
    format("~w~n", [Label]),
    format("   conditions: ~w~n", [Conditions]),
    format("   conflict set (~d): ~w~n", [N, ActualSet]),
    format("   ~w~n", [Comment]),
    format("   [~w]~n~n", [Mark]).

run_order_experiment(Status) :-
    retractall(condition(_)),
    Conditions = [computer_not_start, power_present, fan_not_work, monitor_not_work],
    forall(member(C, Conditions), assert(condition(C))),
    findall(X, action(X), OriginalSet),
    findall(X, action_swapped(X), SwappedSet),
    OriginalSet = [OriginalFirst | _],
    SwappedSet = [SwappedFirst | _],
    (   OriginalFirst \== SwappedFirst
    ->  Status = ok, Mark = ok
    ;   Status = failed, Mark = 'MISMATCH'
    ),
    format("Rule-order experiment (lab step 11):~n"),
    format("   original clause order  -> first = ~w~n", [OriginalFirst]),
    format("   rules 2 and 3 swapped   -> first = ~w~n", [SwappedFirst]),
    format("   swapping the two conflicting rules changes which diagnosis wins~n"),
    format("   [~w]~n~n", [Mark]),
    retractall(condition(_)).

main :-
    format("~nKnowledge base: knowledge_base.pl (SWI-Prolog)~n"),
    format("======================================================================~n~n"),
    findall(S, run_scenario(S), ScenarioStatuses),
    run_order_experiment(OrderStatus),
    append(ScenarioStatuses, [OrderStatus], All),
    length(ScenarioStatuses, NS),
    format("======================================================================~n"),
    % Guards against a clause being silently dropped by a syntax error:
    % without it a missing scenario would still report success.
    (   NS =:= 8 -> true
    ;   format("ERROR: expected 8 scenarios, loaded ~d~n", [NS]), fail
    ),
    (   memberchk(failed, All)
    ->  format("SOME CHECKS FAILED~n")
    ;   length(All, Total),
        format("ALL ~d CHECKS PASSED (~d scenarios + 1 rule-order experiment)~n", [Total, NS])
    ).
