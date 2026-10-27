"""Opponent range estimation + Monte Carlo equity. Shared by the bots and the hand analyzer.

A 'view' is a plain dict so both a live Hand and a stored hand record can feed it:
  {"positions": {seat: "BTN"...}, "actions": [...], "board": [...], "bb": int}
"""
import random

from .cards import ALL_COMBOS, evaluate, hand_class
from .preflop_data import ORDER

CLASS_RANK = {c: i for i, c in enumerate(ORDER)}
SORTED_COMBOS = sorted(ALL_COMBOS, key=lambda cb: CLASS_RANK[hand_class(list(cb))])
_N = len(SORTED_COMBOS)

# fraction of combos strictly better than each class (0.0 = AA)
CLASS_PCT = {}
_acc = 0
for _cls in ORDER:
    CLASS_PCT[_cls] = _acc / _N
    _acc += 6 if len(_cls) == 2 else (4 if _cls.endswith("s") else 12)


def hand_pct(hole):
    return CLASS_PCT[hand_class(hole)]


# Baseline (solid regular) preflop ranges, as fraction of all combos.
BASE_OPEN = {"UTG": 0.15, "HJ": 0.19, "CO": 0.27, "BTN": 0.45, "SB": 0.38, "BB": 0.25, "MP": 0.17}
BASE_CALL = {"UTG": 0.07, "HJ": 0.08, "CO": 0.10, "BTN": 0.14, "SB": 0.07, "BB": 0.32, "MP": 0.08}
BASE_3BET = 0.05
BASE_4BET = 0.022


# ---------------------------------------------------------------- preflop read
def preflop_summary(view, seat):
    """Describe a seat's preflop line: returns (kind, raises_before_their_last_action)."""
    raises = 0
    kind = None
    for a in view["actions"]:
        if a["street"] != "preflop":
            break
        if a["type"] in ("post_sb", "post_bb", "uncalled", "collect", "deal"):
            continue
        if a["seat"] == seat:
            if a["type"] == "raise":
                kind = ("open" if raises == 0 else "3bet" if raises == 1 else "4bet")
            elif a["type"] == "call":
                kind = ("limp" if raises == 0 else "call" if raises == 1 else
                        "call3" if raises == 2 else "call4")
            elif a["type"] == "check":
                kind = kind or "check"
            elif a["type"] == "fold":
                kind = "fold"
        if a["type"] == "raise":
            raises += 1
    return kind


def preflop_band(view, seat, loose=1.0):
    """(lo, hi) fraction band of SORTED_COMBOS for a seat's preflop action."""
    pos = view["positions"].get(seat, "MP")
    kind = preflop_summary(view, seat)
    if kind is None or kind == "check":
        band = (0.0, 1.0)
    elif kind == "open":
        band = (0.0, BASE_OPEN.get(pos, 0.2) * 1.1)
    elif kind == "limp":
        band = (0.02, 0.6) if pos != "SB" else (0.0, 0.75)
    elif kind == "call":
        band = (0.02, 0.42) if pos == "BB" else (0.025, 0.24)
    elif kind == "3bet":
        band = (0.0, 0.075)
    elif kind == "call3":
        band = (0.008, 0.12)
    elif kind == "4bet":
        band = (0.0, 0.03)
    else:  # call4 or more
        band = (0.0, 0.035)
    lo, hi = band
    return (lo * min(loose, 1.0), min(1.0, hi * loose))


# ---------------------------------------------------------------- postflop read
def _made_and_draw(hole, board):
    """Quick strength buckets: 'strong', 'pair', 'draw', 'air'."""
    full = evaluate(hole + board)
    bscore = evaluate(board) if len(board) >= 5 else None
    cat = full >> 20
    bcat = (bscore >> 20) if bscore is not None else _board_cat(board)
    top_board = max(c >> 2 for c in board)
    if cat >= 2 and cat > bcat:
        return "strong"
    if cat == 1 and bcat == 0:
        pr = (full >> 16) & 15
        if pr >= top_board:
            return "strong" if pr >= 9 else "pair"   # top pair / overpair; weaker kickers as pair
        return "pair"
    if cat > bcat:
        return "pair"
    if len(board) < 5 and _has_draw(hole, board):
        return "draw"
    return "air"


def _board_cat(board):
    ranks = [c >> 2 for c in board]
    m = max(ranks.count(r) for r in set(ranks))
    return {1: 0, 2: 1, 3: 3, 4: 7}[m] if len(board) < 5 else 0


def _has_draw(hole, board):
    cards = hole + board
    for s in range(4):
        n = sum(1 for c in cards if c & 3 == s)
        if n == 4 and any(c & 3 == s for c in hole):
            return True
    # bit r+1 for each rank; ace also at bit 0 (wheel draws)
    mask = 0
    for c in cards:
        r = c >> 2
        mask |= 1 << (r + 1)
        if r == 12:
            mask |= 1
    hm = 0
    for c in hole:
        r = c >> 2
        hm |= 1 << (r + 1)
        if r == 12:
            hm |= 1
    for low in range(0, 10):
        window = 0b11111 << low
        if bin(mask & window).count("1") == 4 and (hm & window):
            # open-ended (both ends free) or gutshot both count as a draw
            return True
    return False


ACCEPT_BET = {"strong": 1.0, "pair": 0.6, "draw": 0.65, "air": 0.25}
ACCEPT_RAISE = {"strong": 1.0, "pair": 0.3, "draw": 0.45, "air": 0.12}
ACCEPT_CALL = {"strong": 0.9, "pair": 1.0, "draw": 0.9, "air": 0.2}
ACCEPT_CHECK = {"strong": 0.55, "pair": 1.0, "draw": 1.0, "air": 1.0}


def _postflop_lines(view, seat):
    """[(board_len, kind)] for each postflop action by seat."""
    out = []
    for a in view["actions"]:
        if a["street"] in ("preflop", "showdown") or a["seat"] != seat:
            continue
        t = a["type"]
        if t in ("bet", "raise", "call", "check"):
            kind = t
            if t == "raise" and a.get("current_bet_before", 1) == 0:
                kind = "bet"
            out.append((a["board_len"], kind))
    return out


def estimate_range(view, seat, dead, loose=1.0, postflop=True):
    """Weighted list [(combo, weight)] for a seat, excluding dead cards."""
    lo, hi = preflop_band(view, seat, loose)
    a, b = int(lo * _N), max(int(hi * _N), int(lo * _N) + 12)
    combos = [cb for cb in SORTED_COMBOS[a:b] if cb[0] not in dead and cb[1] not in dead]
    lines = _postflop_lines(view, seat) if postflop else []
    board = view["board"]
    out = []
    for cb in combos:
        w = 1.0
        for blen, kind in lines:
            if blen < 3:
                continue
            bucket = _made_and_draw(list(cb), board[:blen])
            tbl = (ACCEPT_BET if kind == "bet" else ACCEPT_RAISE if kind == "raise"
                   else ACCEPT_CALL if kind == "call" else ACCEPT_CHECK)
            w *= tbl[bucket]
        if w > 0.001:
            out.append((cb, w))
    if not out:  # fall back to anything not dead
        out = [(cb, 1.0) for cb in ALL_COMBOS if cb[0] not in dead and cb[1] not in dead]
    return out


# ---------------------------------------------------------------- equity
def _cum(weighted):
    cum, t = [], 0.0
    for _, w in weighted:
        t += w
        cum.append(t)
    return cum


def equity_vs_ranges(hero, board, ranges, samples=600, rng=None):
    """hero equity (0..1, ties split) vs a list of weighted ranges."""
    rng = rng or random
    if not ranges:
        return 1.0
    cums = [(r, _cum(r)) for r in ranges]
    dead0 = set(hero) | set(board)
    need = 5 - len(board)
    total = 0.0
    done = 0
    import bisect
    for _ in range(samples):
        used = set(dead0)
        vill = []
        ok = True
        for r, cum in cums:
            for _try in range(25):
                x = rng.random() * cum[-1]
                cb = r[bisect.bisect_left(cum, x)][0]
                if cb[0] not in used and cb[1] not in used:
                    break
            else:
                ok = False
                break
            used.add(cb[0])
            used.add(cb[1])
            vill.append(cb)
        if not ok:
            continue
        if need:
            deck = [c for c in range(52) if c not in used]
            full = board + rng.sample(deck, need)
        else:
            full = board
        h = evaluate(hero + full)
        best, ties = 0, 0
        for cb in vill:
            v = evaluate([cb[0], cb[1]] + full)
            if v > best:
                best, ties = v, 1
            elif v == best:
                ties += 1
        if h > best:
            total += 1
        elif h == best:
            total += 1.0 / (ties + 1)
        done += 1
    return total / done if done else 0.5


def equity_vs_hands(hero, board, villains, samples=3000, rng=None):
    """Exact (flop/turn/river) or Monte Carlo (preflop) equity vs known hands."""
    rng = rng or random
    if not villains:
        return 1.0
    used = set(hero) | set(board)
    for v in villains:
        used |= set(v)
    deck = [c for c in range(52) if c not in used]
    need = 5 - len(board)
    if need == 0:
        runouts = [[]]
    elif need == 1:
        runouts = [[c] for c in deck]
    elif need == 2:
        runouts = [[deck[i], deck[j]] for i in range(len(deck)) for j in range(i)]
    else:
        runouts = [rng.sample(deck, need) for _ in range(samples)]
    total = 0.0
    for ro in runouts:
        full = board + ro
        h = evaluate(hero + full)
        best, ties = 0, 0
        for v in villains:
            s = evaluate(list(v) + full)
            if s > best:
                best, ties = s, 1
            elif s == best:
                ties += 1
        if h > best:
            total += 1
        elif h == best:
            total += 1.0 / (ties + 1)
    return total / len(runouts)


def has_draw(hole, board):
    return len(board) < 5 and _has_draw(hole, board)
