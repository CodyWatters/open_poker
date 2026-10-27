"""Hand analysis: per-decision equity + grading, all-in EV, per-hand facts, aggregate stats."""
import random
from itertools import combinations

from .cards import evaluate, hand_class, cards_str
from .ranges import (estimate_range, equity_vs_ranges, equity_vs_hands, hand_pct, has_draw,
                     open_pct, call_pct)

PLAYER_ACTS = ("fold", "check", "call", "bet", "raise")
ANALYSIS_VERSION = 2


def _positions(rec):
    return {s["seat"]: s["position"] for s in rec["seats"]}


def _holes(rec):
    return {s["seat"]: s["hole"] for s in rec["seats"]}


def _folded_before(rec, idx):
    return {a["seat"] for a in rec["actions"][:idx] if a["type"] == "fold"}


# ------------------------------------------------------------------ facts (cheap)
def hand_facts(rec):
    hero = rec["hero_seat"]
    acts = rec["actions"]
    pos = _positions(rec)[hero]
    bb = rec["bb"]
    f = dict(vpip=0, pfr=0, tb_opp=0, tb=0, saw_flop=0, wtsd=0, wsd=0, cbet_opp=0, cbet=0,
             ftc_opp=0, ftc=0, agg=0, calls=0, position=pos)
    raises = 0
    last_raiser = None
    hero_first_after_raise = True
    for a in acts:
        if a["street"] != "preflop":
            break
        if a["seat"] == hero and a["type"] in PLAYER_ACTS:
            if a["type"] in ("call", "raise"):
                f["vpip"] = 1
            if a["type"] == "raise":
                f["pfr"] = 1
            if raises == 1 and hero_first_after_raise:
                f["tb_opp"] = 1
                hero_first_after_raise = False
                if a["type"] == "raise":
                    f["tb"] = 1
        if a["type"] == "raise":
            raises += 1
            last_raiser = a["seat"]
    folded = {a["seat"]: a["street"] for a in acts if a["type"] == "fold"}
    hero_fold_street = folded.get(hero)
    saw_flop = len(rec["board"]) >= 3 and hero_fold_street != "preflop" and any(
        a["street"] == "flop" for a in acts)
    # all-in preflop runouts still count as seeing the flop
    f["saw_flop"] = 1 if saw_flop else 0
    if rec["showdown"] and hero not in folded:
        f["wtsd"] = 1 if saw_flop else 0
        f["wsd"] = 1 if rec["collected"].get(str(hero), 0) > 0 else 0
    # c-bet / fold to c-bet
    flop_acts = [a for a in acts if a["street"] == "flop" and a["type"] in PLAYER_ACTS]
    if saw_flop and flop_acts:
        if last_raiser == hero:
            first_bet_seen = False
            for a in flop_acts:
                if a["seat"] == hero:
                    if not first_bet_seen:
                        f["cbet_opp"] = 1
                        f["cbet"] = 1 if a["type"] == "bet" else 0
                    break
                if a["type"] in ("bet", "raise"):
                    first_bet_seen = True
        elif last_raiser is not None:
            first_bet = next((a for a in flop_acts if a["type"] == "bet"), None)
            if first_bet and first_bet["seat"] == last_raiser:
                after = [a for a in flop_acts if a["i"] > first_bet["i"] and a["seat"] == hero]
                if after:
                    f["ftc_opp"] = 1
                    f["ftc"] = 1 if after[0]["type"] == "fold" else 0
    for a in acts:
        if a["seat"] == hero and a["street"] not in ("preflop",) and a["type"] in PLAYER_ACTS:
            if a["type"] in ("bet", "raise"):
                f["agg"] += 1
            elif a["type"] == "call":
                f["calls"] += 1
    net = rec["hero_net"]
    f["net"] = net
    f["net_bb"] = net / bb
    return f


# ------------------------------------------------------------------ pots / all-in EV
def _award(board, holes, pots):
    scores = {s: evaluate(holes[s] + board) for s in holes}
    won = {}
    for pot in pots:
        elig = [s for s in pot["eligible"] if s in scores]
        if not elig:
            continue
        best = max(scores[s] for s in elig)
        w = [s for s in elig if scores[s] == best]
        for s in w:
            won[s] = won.get(s, 0) + pot["amount"] / len(w)
    return won


def allin_ev(rec, rng):
    """If money went in before the river was dealt, return hero's expected net (else None)."""
    if not rec["showdown"]:
        return None
    hero = rec["hero_seat"]
    live = [s["seat"] for s in rec["seats"] if s["seat"] not in
            {a["seat"] for a in rec["actions"] if a["type"] == "fold"} and s["hole"]]
    if hero not in live:
        return None
    lock = max((a["board_len"] for a in rec["actions"] if a["type"] in PLAYER_ACTS), default=0)
    if lock >= 5:
        return None
    board = rec["board"][:lock]
    holes = {s: _holes(rec)[s] for s in live}
    used = set(board)
    for h in holes.values():
        used |= set(h)
    deck = [c for c in range(52) if c not in used]
    need = 5 - lock
    if need <= 2:
        runouts = [list(c) for c in combinations(deck, need)]
    else:
        runouts = [rng.sample(deck, need) for _ in range(2500)]
    tot = 0.0
    for ro in runouts:
        tot += _award(board + ro, holes, rec["pots"]).get(hero, 0)
    exp = tot / len(runouts)
    invested = next(s["invested"] for s in rec["seats"] if s["seat"] == hero)
    eq = equity_vs_hands(holes[hero], board, [holes[s] for s in live if s != hero], rng=rng)
    return {"ev_net": round(exp - invested, 2), "equity": round(eq, 4), "board_len": lock,
            "actual_net": rec["hero_net"], "luck": round(rec["hero_net"] - (exp - invested), 2)}


# ------------------------------------------------------------------ decisions
def _preflop_ctx(actions, idx):
    raises = 0
    for a in actions[:idx]:
        if a["street"] != "preflop":
            break
        if a["type"] == "raise":
            raises += 1
    return raises


def _pct_txt(x):
    return "%d%%" % round(x * 100)


def grade_preflop(rec, a, idx, hole, pos):
    n = len(rec["seats"])
    raises = _preflop_ctx(rec["actions"], idx)
    pct = hand_pct(hole)
    cls = hand_class(hole)
    t = a["type"]
    out = []
    if raises == 0:
        open_r = open_pct(pos, n)
        if pos == "BB":
            pass
        elif t == "fold" and pct < open_r * 0.8:
            out.append(("note", "Tight fold: %s is in a standard %s opening range (top %s of hands)."
                        % (cls, pos, _pct_txt(open_r))))
        elif t == "raise" and pct > open_r * 1.7:
            out.append(("note", "Loose open: %s is outside a standard %s range (top %s)."
                        % (cls, pos, _pct_txt(open_r))))
        elif t == "call" and pos != "SB":
            out.append(("note", "Open-limp: raising or folding is usually better than limping."))
    elif raises == 1:
        call_r = call_pct(pos, n)
        if t == "fold" and pct < 0.03:
            out.append(("mistake", "Folded a premium hand (%s) to a single raise." % cls))
        elif t == "call" and pct > call_r * 2 and pos != "BB":
            out.append(("note", "Loose call vs a raise: %s is wider than a typical %s calling range."
                        % (cls, pos)))
        elif t == "call" and pos == "BB" and pct > 0.6:
            out.append(("note", "Very wide BB defend with %s." % cls))
    else:
        if t == "fold" and pct < 0.012:
            out.append(("mistake", "Folded %s facing a re-raise. This is usually a continue." % cls))
        elif t == "call" and pct > 0.12:
            out.append(("note", "Calling a re-raise with %s is loose." % cls))
    return out



# ------------------------------------------------------------------ "what you should have done" (simple advice)
AGGRO = ("bet", "raise")


def _same(hero_action, rec_action):
    a = "aggro" if hero_action in AGGRO else hero_action
    b = "aggro" if rec_action in AGGRO else rec_action
    return a == b


def should_have(street, hero_action, hole, pos, raises_before, to_call, req, eq, opps, draw, bb, was_pfr=False, n=6):
    """Return {'action', 'label', 'why', 'match', 'close'} in plain language."""
    cls = hand_class(hole)
    pc = lambda x: "%d%%" % round(x * 100)
    close = False
    if street == "preflop":
        pct = hand_pct(hole)
        if raises_before == 0:
            if pos == "BB" and not to_call:
                if pct < 0.10:
                    act, label, why = "raise", "Raise", "%s is a top hand. Raise the limpers to win more." % cls
                else:
                    act, label, why = "check", "Check", "You can see the flop for free with %s." % cls
            else:
                rng = open_pct(pos, n)
                if pct < rng:
                    act, label = "raise", "Raise (about %s)" % ("3x the big blind" if pos == "SB" else "2.5x the big blind")
                    why = "%s is strong enough to open from %s (top %s of hands). Raise rather than just call." % (cls, pos, pc(rng))
                    close = pct > rng * 0.85
                else:
                    act, label = "fold", "Fold"
                    why = "%s is too weak to play from %s. Good players fold it here." % (cls, pos)
                    close = pct < rng * 1.15
        elif raises_before == 1:
            call_r = call_pct(pos, n)
            if pct < 0.05:
                act, label, why = "raise", "Re-raise (3-bet)", "%s is a premium hand. Re-raise to build a bigger pot." % cls
            elif pct < call_r:
                act, label, why = "call", "Call", "%s is good enough to call a single raise from %s." % (cls, pos)
                close = pct > call_r * 0.85
            else:
                act, label, why = "fold", "Fold", "%s isn't strong enough to call a raise from %s." % (cls, pos)
                close = pct < call_r * 1.2
        else:
            if pct < 0.022:
                act, label, why = "raise", "Re-raise / go all-in", "%s is one of the very best hands. Put the money in." % cls
            elif pct < 0.07:
                act, label, why = "call", "Call", "%s is strong enough to call a re-raise." % cls
                close = True
            else:
                act, label, why = "fold", "Fold", "Facing a re-raise, %s is usually beaten. Fold." % cls
    else:
        value_t = 0.60 + 0.07 * max(0, opps - 1)
        if to_call:
            implied = 0.05 if (draw and street != "river") else 0.0
            if eq >= 0.72 + 0.05 * max(0, opps - 1):
                act, label = "raise", "Raise"
                why = "You likely have the best hand (about %s). Raise to win a bigger pot." % pc(eq)
                close = eq < 0.78
            elif eq + implied >= req:
                act, label = "call", "Call"
                if draw and eq < req:
                    why = "You're drawing (about %s now). The pot price plus what you can win later makes calling OK." % pc(eq)
                else:
                    why = "You needed %s to call and had about %s. Calling wins money over time." % (pc(req), pc(eq))
                close = abs(eq + implied - req) < 0.05
            else:
                act, label = "fold", "Fold"
                why = "You needed %s to call but only had about %s. Calling loses money over time." % (pc(req), pc(eq))
                close = abs(eq + implied - req) < 0.05
        else:
            if eq >= value_t:
                act, label = "bet", "Bet (about half to two-thirds of the pot)"
                why = "Your hand is strong (about %s). Bet so worse hands pay you." % pc(eq)
                close = eq < value_t + 0.05
            elif was_pfr and street == "flop" and opps <= 2:
                act, label = "check", "Check, or a small bet (continuation bet)"
                why = "You raised before the flop, so a small bet (about a third of the pot) often takes it down. Checking is also fine."
                close = True
            elif draw and street != "river" and opps == 1:
                act, label = "check", "Check (or a small bet as a semi-bluff)"
                why = "You have a draw. Checking is fine; betting can also win the pot right away."
                close = True
            else:
                act, label = "check", "Check"
                why = "Your hand is about %s. Not strong enough to bet for value, so check." % pc(eq)
                close = eq > value_t - 0.05
    match = _same(hero_action, act) or (close and hero_action != "fold" and act != "fold")
    return {"action": act, "label": label, "why": why, "match": bool(match), "close": bool(close)}

def analyze(rec, rng=None, samples=1200):
    rng = rng or random.Random(rec["id"])
    hero = rec["hero_seat"]
    holes = _holes(rec)
    hole = holes[hero]
    positions = _positions(rec)
    pos = positions[hero]
    decisions = []
    pfr = None
    for a in rec["actions"]:
        if a["street"] == "preflop" and a["type"] == "raise":
            pfr = a["seat"]
    for idx, a in enumerate(rec["actions"]):
        if a["seat"] != hero or a["type"] not in PLAYER_ACTS:
            continue
        street = a["street"]
        board = rec["board"][:a["board_len"]]
        view = {"positions": positions, "actions": rec["actions"][:idx], "board": board, "bb": rec["bb"]}
        folded = _folded_before(rec, idx)
        opps = [s["seat"] for s in rec["seats"] if s["seat"] != hero and s["seat"] not in folded and s["hole"]]
        dead = set(hole) | set(board)
        ranges = [estimate_range(view, s, dead, postflop=True) for s in opps]
        eq_r = equity_vs_ranges(hole, board, ranges, samples=samples, rng=rng)
        eq_a = equity_vs_hands(hole, board, [holes[s] for s in opps], samples=2000, rng=rng)
        to_call = a.get("to_call", 0)
        pot = a.get("pot_before", 0)
        req = to_call / (pot + to_call) if to_call else 0.0
        flags = []
        if street == "preflop":
            flags += grade_preflop(rec, a, idx, hole, pos)
        else:
            draw = has_draw(hole, board)
            t = a["type"]
            implied = 0.05 if (draw and street != "river") else 0.0
            if t == "fold" and to_call:
                m = eq_r - req
                if m > 0.10:
                    flags.append(("mistake", "Folded with ~%s equity vs likely ranges; only needed %s."
                                  % (_pct_txt(eq_r), _pct_txt(req))))
                elif m > 0.04:
                    flags.append(("note", "Close fold: ~%s equity vs %s needed." % (_pct_txt(eq_r), _pct_txt(req))))
            elif t == "call":
                m = eq_r + implied - req
                if m < -0.12:
                    flags.append(("mistake", "Called needing %s with only ~%s equity vs likely ranges."
                                  % (_pct_txt(req), _pct_txt(eq_r))))
                elif m < -0.05:
                    flags.append(("note", "Thin call: ~%s equity vs %s needed." % (_pct_txt(eq_r), _pct_txt(req))))
            elif t == "check" and not to_call:
                if street == "river" and eq_r > 0.75 and len(opps) == 1:
                    flags.append(("note", "Missed value? Checked the river with ~%s equity." % _pct_txt(eq_r)))
                elif eq_r > 0.85 and len(opps) <= 2:
                    flags.append(("note", "Slow-played a very strong hand (~%s)." % _pct_txt(eq_r)))
            elif t in ("bet", "raise"):
                if eq_r < 0.30:
                    kind = "Semi-bluff" if draw else "Bluff"
                    flags.append(("info", "%s (~%s equity vs likely ranges)." % (kind, _pct_txt(eq_r))))
                elif street == "river" and eq_r < 0.5 and t == "bet":
                    flags.append(("note", "River bet with a medium hand (~%s): worse hands may fold, better hands call."
                                  % _pct_txt(eq_r)))
        if to_call and eq_a >= req and a["type"] == "fold":
            flags.append(("hindsight", "Hindsight: vs their actual cards you had %s (needed %s)."
                          % (_pct_txt(eq_a), _pct_txt(req))))
        decisions.append({
            "i": idx, "street": street, "action": a["type"], "amount": a.get("to") if a["type"] in ("bet", "raise") else a.get("amount", 0),
            "pot": pot, "to_call": to_call, "req": round(req, 4),
            "eq_range": round(eq_r, 4), "eq_actual": round(eq_a, 4), "opponents": len(opps),
            "board": cards_str(board), "flags": [{"level": l, "text": t} for l, t in flags],
            "call_ev": round(eq_r * (pot + to_call) - to_call, 2) if to_call else None,
            "should": should_have(street, a["type"], hole, pos, _preflop_ctx(rec["actions"], idx) if street == "preflop" else 0,
                                  to_call, req, eq_r, len(opps), has_draw(hole, board), rec["bb"], was_pfr=(pfr == hero), n=len(rec["seats"])),
        })
    ev = allin_ev(rec, rng)
    mistakes = sum(1 for d in decisions for f in d["flags"] if f["level"] == "mistake")
    notes = sum(1 for d in decisions for f in d["flags"] if f["level"] == "note")
    return {"v": ANALYSIS_VERSION, "decisions": decisions, "allin": ev, "mistakes": mistakes, "notes": notes,
            "ev_net": ev["ev_net"] if ev else rec["hero_net"]}


# ------------------------------------------------------------------ aggregate stats
def aggregate(rows):
    """rows: list of dicts with keys facts(dict), bb, net, ev_net, ts, stakes_id, mistakes."""
    def ratio(a, b):
        return round(100.0 * a / b, 1) if b else None

    def block(rs):
        n = len(rs)
        s = lambda k: sum(r["facts"].get(k, 0) for r in rs)
        net = sum(r["net"] for r in rs)
        bbs = sum(r["net"] / r["bb"] for r in rs)
        agg, calls = s("agg"), s("calls")
        return {
            "hands": n, "net": net, "bb100": round(100 * bbs / n, 2) if n else None,
            "vpip": ratio(s("vpip"), n), "pfr": ratio(s("pfr"), n),
            "three_bet": ratio(s("tb"), s("tb_opp")), "af": round(agg / calls, 2) if calls else None,
            "wtsd": ratio(s("wtsd"), s("saw_flop")), "wsd": ratio(s("wsd"), s("wtsd")),
            "cbet": ratio(s("cbet"), s("cbet_opp")), "fold_to_cbet": ratio(s("ftc"), s("ftc_opp")),
            "saw_flop": ratio(s("saw_flop"), n),
            "mistakes": sum(r.get("mistakes") or 0 for r in rs),
        }

    overall = block(rows)
    by_pos = {}
    for p in ["UTG", "UTG+1", "UTG+2", "MP", "LJ", "HJ", "CO", "BTN", "SB", "BB"]:
        rs = [r for r in rows if r["facts"].get("position") == p]
        if rs:
            by_pos[p] = block(rs)
    by_stakes = {}
    for r in rows:
        by_stakes.setdefault(r["stakes_id"], []).append(r)
    by_stakes = {k: block(v) for k, v in by_stakes.items()}
    # cumulative series
    cum = cum_ev = cum_sd = cum_nsd = 0.0
    series = []
    for k, r in enumerate(rows):
        cum += r["net"]
        cum_ev += r["ev_net"] if r["ev_net"] is not None else r["net"]
        if r["facts"].get("wtsd") or r.get("showdown_hero"):
            cum_sd += r["net"]
        else:
            cum_nsd += r["net"]
        series.append([k + 1, round(cum, 2), round(cum_ev, 2), round(cum_sd, 2), round(cum_nsd, 2), r["id"]])
    return {"overall": overall, "by_position": by_pos, "by_stakes": by_stakes, "series": series}


# ------------------------------------------------------------------ preflop range chart (13x13)
def _rep_hole(cls):
    """Two concrete cards for a hand class like 'AKs', 'AKo', 'TT'."""
    from .cards import RANKS
    r1, r2 = RANKS.index(cls[0]), RANKS.index(cls[1])
    if len(cls) == 2:
        return [r1 * 4, r2 * 4 + 1]
    if cls[2] == "s":
        return [r1 * 4, r2 * 4]
    return [r1 * 4, r2 * 4 + 1]


def preflop_chart(pos, raises_before, bb_unopened=False, n=6):
    """{hand_class: 'raise'|'call'|'check'|'fold'} using the same advice logic as hand analysis."""
    from .preflop_data import ORDER
    out = {}
    for cls in ORDER:
        sh = should_have("preflop", "fold", _rep_hole(cls), pos, raises_before,
                         0 if bb_unopened else 1, 0, 0, 1, False, 1, n=n)
        out[cls] = sh["action"]
    return out
