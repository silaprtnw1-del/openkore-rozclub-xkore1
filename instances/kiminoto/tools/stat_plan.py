#!/usr/bin/env python3
"""Stat-point planner for the Acolyte "kiminoto".

Rules of this build (set by the owner, 2026-11-06):
  * STR stays at its current value - never add more.
  * AGI and LUK are never raised.
  * Priority: INT 60..65, then DEX 25..30, everything affordable left goes to VIT.
  * The full support skill build (Blessing, Increase AGI, Heal) is untouched.

The planner never assumes how many points the character has. It takes the real
numbers from the game (OpenKore's `st` output), CHECKS the standard stat-point
rules against them, and only plans when they match:

  1. server's cost of the next point of every stat  == 2 + (current - 1) // 10
  2. points spent so far + unspent points            == 48 + sum((L + 14) // 5 for L in 2..level)

If one of the two does not match, the server uses other rules: the script says so
and stops (exit code 2) instead of guessing.  `--accept-offset` re-plans with the
difference in the starting budget, but only when rule 1 holds.

Usage (all numbers are BASE values, without the +bonus part):
  python stat_plan.py --st-file st.txt --level 9
  python stat_plan.py --level 9 --str 16 --agi 1 --vit 1 --int 1 --dex 1 --luk 1 --free 41
  options: --target-level 50   --floors-only   --accept-offset   --self-test
"""
import argparse
import re
import sys

STATS = ("str", "agi", "vit", "int", "dex", "luk")
START_POINTS = 48          # status points of a new character
MAX_STAT = 99
# Build priorities, in this order: (stat, value to reach)
GOALS = (("int", 60), ("dex", 25), ("int", 65), ("dex", 30))
# --floors-only: stop at the lower ends and give everything else to VIT
GOALS_FLOORS = (("int", 60), ("dex", 25))
NEVER_RAISE = ("str", "agi", "luk")


def gain_at(level):
    """Points received when reaching `level`."""
    return (level + 14) // 5


def total_points(level, start=START_POINTS):
    """All status points a character has earned at base `level` (spent + unspent)."""
    return start + sum(gain_at(lv) for lv in range(2, level + 1))


def step_cost(value):
    """Points needed to raise a stat from `value` to `value + 1`."""
    return 2 + (value - 1) // 10


def cost(a, b):
    """Points needed to raise one stat from `a` to `b`."""
    return sum(step_cost(n) for n in range(a, b)) if b > a else 0


def level_for_budget(points, offset=0):
    """Lowest base level whose earned points (plus offset) reach `points`."""
    for lv in range(1, 100):
        if total_points(lv) + offset >= points:
            return lv
    return None


def parse_st(text):
    """Parse OpenKore's `st` output: 'Str: 16 +0  #3 ...' and 'Status Points: 41'."""
    cur, nxt = {}, {}
    for m in re.finditer(r"\b(Str|Agi|Vit|Int|Dex|Luk):\s*(\d+)\s*\+\s*(\d+)\s*#\s*(\d+)", text, re.I):
        cur[m.group(1).lower()] = int(m.group(2))
        nxt[m.group(1).lower()] = int(m.group(4))
    m = re.search(r"Status Points:\s*(\d+)", text, re.I)
    free = int(m.group(1)) if m else None
    return cur, nxt, free


def validate(cur, free, level, reported_costs):
    """Returns (problems, offset). offset = real total - formula total at `level`."""
    problems = []
    for s in STATS:
        if s in reported_costs and reported_costs[s] != step_cost(cur[s]):
            problems.append(
                f"{s.upper()} {cur[s]}: the server asks {reported_costs[s]} points for the next point, "
                f"the standard rule says {step_cost(cur[s])}")
    spent = sum(cost(1, cur[s]) for s in STATS)
    real_total = spent + free
    offset = real_total - total_points(level)
    return problems, offset, spent, real_total


def make_plan(cur, free, level, target_level, offset, goals=GOALS):
    spent_now = sum(cost(1, cur[s]) for s in STATS)
    budget = total_points(target_level) + offset
    available = budget - spent_now            # points that can still be spent by target_level
    plan = dict(cur)
    steps = []                                # (stat, value reached, cumulative points)
    used = 0

    def raise_to(stat, goal):
        nonlocal used
        complete = True
        while plan[stat] < goal:
            c = step_cost(plan[stat])
            if used + c > available:
                complete = False
                break
            plan[stat] += 1
            used += c
        return complete

    for stat, goal in goals:
        assert stat not in NEVER_RAISE
        if plan[stat] >= goal:
            continue
        before = plan[stat]
        complete = raise_to(stat, goal)
        if plan[stat] > before:
            steps.append((stat, plan[stat], used))
        if not complete:
            break                              # strict priority: no skipping to a lower goal
    before = plan["vit"]
    while plan["vit"] < MAX_STAT and used + step_cost(plan["vit"]) <= available:
        used += step_cost(plan["vit"])
        plan["vit"] += 1
    if plan["vit"] > before:
        steps.append(("vit", plan["vit"], used))
    return plan, steps, available, used, budget


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--level", type=int, help="current base level")
    ap.add_argument("--target-level", type=int, default=50)
    ap.add_argument("--st-file", help="file with the pasted output of OpenKore's `st` command")
    ap.add_argument("--free", type=int, help="unspent status points")
    for s in STATS:
        ap.add_argument("--" + s, type=int, help=f"current base {s.upper()}")
    ap.add_argument("--floors-only", action="store_true",
                    help="stop at INT 60 / DEX 25 and put all remaining points into VIT")
    ap.add_argument("--accept-offset", action="store_true",
                    help="plan even if the starting budget differs from the standard 48 points")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)

    if a.self_test:
        return self_test()

    cur, reported, free = {}, {}, a.free
    if a.st_file:
        with open(a.st_file, encoding="utf-8", errors="replace") as f:
            cur, reported, free_parsed = parse_st(f.read())
        free = free if free is not None else free_parsed
    for s in STATS:
        v = getattr(a, s)
        if v is not None:
            cur[s] = v
    missing = [s for s in STATS if s not in cur]
    if missing or free is None or a.level is None:
        print("Need the real character data: --level, --free and all six stats (or --st-file from `st`).")
        print("Missing:", ", ".join(missing + ([] if free is not None else ["free"]) + ([] if a.level else ["level"])))
        return 2

    print(f"Current character: base Lv {a.level}, unspent {free}")
    print("  " + "  ".join(f"{s.upper()} {cur[s]}" for s in STATS))
    problems, offset, spent, real_total = validate(cur, free, a.level, reported)
    print(f"Budget check: spent {spent} + unspent {free} = {real_total}; "
          f"standard rule for Lv {a.level} = {total_points(a.level)}  (difference {offset:+d})")
    if reported:
        print("Server cost of the next point: " + ", ".join(f"{s.upper()} {reported[s]}" for s in STATS if s in reported))

    if problems:
        print("\nSTOP - the standard cost rule does not match this server:")
        for p in problems:
            print("  -", p)
        print("The plan cannot be trusted. Send these numbers back so the rule can be derived from them.")
        return 2
    if offset != 0 and not a.accept_offset:
        print(f"\nSTOP - the real budget differs from the standard rule by {offset:+d} points.")
        print("Possible causes: other start points / per-level gains on this server, a reset, or a typo in the numbers.")
        print("Re-run with --accept-offset to plan with the standard per-level gains plus this fixed difference.")
        return 2
    if a.target_level < a.level:
        print("target level is below the current level")
        return 2

    goals = GOALS_FLOORS if a.floors_only else GOALS
    plan, steps, available, used, budget = make_plan(cur, free, a.level, a.target_level, offset, goals)
    print(f"\nBudget at Base Lv {a.target_level}: {budget} points in total "
          f"({'standard rule' if offset == 0 else f'standard rule {offset:+d}'}); "
          f"{available} can still be spent from now on.")
    if a.floors_only:
        print("Build rules: STR/AGI/LUK never raised; order INT 60, DEX 25, then all remaining points to VIT (floors only).\n")
    else:
        print("Build rules: STR/AGI/LUK never raised; order INT 60, DEX 25, INT 65, DEX 30, then VIT.\n")
    print(f"{'step':<28}{'points':>8}{'total':>8}   reachable at base Lv")
    prev = 0
    for stat, value, cum in steps:
        print(f"{stat.upper() + ' -> ' + str(value):<28}{cum - prev:>8}{cum:>8}   {level_for_budget(spent + cum, offset)}")
        prev = cum
    print(f"\nResult at Lv {a.target_level}: " + "  ".join(f"{s.upper()} {plan[s]}" for s in STATS)
          + f"   (unspent {available - used})")
    assert plan["str"] == cur["str"] and plan["agi"] == cur["agi"] and plan["luk"] == cur["luk"]
    missed = [f"{s.upper()} {g}" for s, g in goals if plan[s] < g]
    if missed:
        print("Not reachable by this level: " + ", ".join(missed))

    # OpenKore's statsAddAuto_list: "<value> <stat>" entries, processed in order
    merged = []
    for stat, value, _ in steps:
        merged.append(f"{value} {stat}")
    print("\nstatsAddAuto_list (keep statsAddAuto 0 until you have checked this):")
    print("  " + ", ".join(merged))
    return 0


def self_test():
    ok = True

    def check(name, got, want):
        nonlocal ok
        flag = "ok " if got == want else "FAIL"
        ok &= got == want
        print(f"  {flag} {name}: {got}" + ("" if got == want else f" (want {want})"))

    print("self-test of the standard rules")
    check("points at Lv 99", total_points(99), 1273)
    check("points at Lv 50", total_points(50), 420)
    check("cost 1->60", cost(1, 60), 263)
    check("cost 1->65", cost(1, 65), 302)
    check("cost 1->25", cost(1, 25), 66)
    check("cost 1->30", cost(1, 30), 86)
    check("cost 1->16", cost(1, 16), 35)
    check("next-point cost at 1/10/11/60/65", [step_cost(n) for n in (1, 10, 11, 60, 65)], [2, 2, 3, 7, 8])
    cur, nxt, free = parse_st("Str: 16 +0  #3  Atk: 5+3  Def: 0+0\nDex: 1  +0  #2  Status Points: 41\n")
    check("parse `st`", (cur.get("str"), nxt.get("str"), cur.get("dex"), free), (16, 3, 1, 41))
    # mismatch detection: a character with 5 extra points must be refused
    probs, off, _, _ = validate({"str": 16, "agi": 1, "vit": 1, "int": 1, "dex": 1, "luk": 1}, 46, 9, {})
    check("detects a +5 budget difference", off, 5)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
