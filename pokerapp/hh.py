"""Export a hand record as PokerStars-format text (importable by PokerTracker, HM3, GTO Wizard, etc.)."""
from datetime import datetime, timezone

from .cards import cards_str

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    _ET = None

STREET_TITLE = {"flop": "Flop", "turn": "Turn", "river": "River"}


def _m(x):
    x = round(x, 2)
    return ("$%d" % x) if x == int(x) else ("$%.2f" % x)


def _ts(rec):
    dt = datetime.fromisoformat(rec["ts"])
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if _ET:
        dt = dt.astimezone(_ET)
    return dt.strftime("%Y/%m/%d %H:%M:%S") + " ET"


def hand_number(rec):
    return 900000000000 + rec["id"]


def to_pokerstars(rec):
    seats = {s["seat"]: s for s in rec["seats"]}
    name = lambda seat: seats[seat]["name"]
    L = []
    L.append("PokerStars Hand #%d:  Hold'em No Limit (%s/%s USD) - %s"
             % (hand_number(rec), _m(rec["sb"]), _m(rec["bb"]), _ts(rec)))
    L.append("Table '%s' %d-max Seat #%d is the button" % (rec["table_name"], rec.get("max_seats", 6), rec["button_seat"]))
    for s in sorted(seats):
        L.append("Seat %d: %s (%s in chips)" % (s, name(s), _m(seats[s]["start_stack"])))
    acts = rec["actions"]
    hole_printed = False
    folded_on = {}
    pots = rec["pots"]
    npots = len(pots)

    def pot_name(k):
        if npots == 1:
            return "pot"
        if k == 0:
            return "main pot"
        return "side pot" if npots == 2 else "side pot-%d" % k

    shown = False
    for a in acts:
        t = a["type"]
        if t in ("post_sb", "post_bb"):
            word = "small" if t == "post_sb" else "big"
            L.append("%s: posts %s blind %s%s" % (name(a["seat"]), word, _m(a["amount"]),
                                                    " and is all-in" if a["allin"] else ""))
            continue
        if not hole_printed and t not in ("post_sb", "post_bb"):
            L.append("*** HOLE CARDS ***")
            L.append("Dealt to %s [%s]" % (name(rec["hero_seat"]), cards_str(seats[rec["hero_seat"]]["hole"])))
            hole_printed = True
        ai = " and is all-in" if a.get("allin") else ""
        if t == "fold":
            L.append("%s: folds" % name(a["seat"]))
            folded_on[a["seat"]] = a["street"]
        elif t == "check":
            L.append("%s: checks" % name(a["seat"]))
        elif t == "call":
            L.append("%s: calls %s%s" % (name(a["seat"]), _m(a["amount"]), ai))
        elif t == "bet":
            L.append("%s: bets %s%s" % (name(a["seat"]), _m(a["to"]), ai))
        elif t == "raise":
            L.append("%s: raises %s to %s%s" % (name(a["seat"]), _m(a["raise_by"]), _m(a["to"]), ai))
        elif t == "uncalled":
            L.append("Uncalled bet (%s) returned to %s" % (_m(a["amount"]), name(a["seat"])))
        elif t == "deal":
            b = a["board"]
            if len(b) == 3:
                L.append("*** FLOP *** [%s]" % cards_str(b))
            elif len(b) == 4:
                L.append("*** TURN *** [%s] [%s]" % (cards_str(b[:3]), cards_str(b[3:])))
            else:
                L.append("*** RIVER *** [%s] [%s]" % (cards_str(b[:4]), cards_str(b[4:])))
        elif t == "collect":
            if rec["showdown"] and not shown:
                L.append("*** SHOW DOWN ***")
                for s in sorted(rec["descriptions"], key=int):
                    L.append("%s: shows [%s] (%s)" % (name(int(s)), cards_str(seats[int(s)]["hole"]),
                                                     rec["descriptions"][s]))
                shown = True
            L.append("%s collected %s from %s" % (name(a["seat"]), _m(a["amount"]), pot_name(a.get("pot_index", 0))))
            if not rec["showdown"]:
                L.append("%s: doesn't show hand" % name(a["seat"]))
    L.append("*** SUMMARY ***")
    total = sum(p["amount"] for p in pots)
    if npots > 1:
        parts = ["Main pot %s." % _m(pots[0]["amount"])]
        for k in range(1, npots):
            label = "Side pot" if npots == 2 else "Side pot-%d" % k
            parts.append("%s %s." % (label, _m(pots[k]["amount"])))
        L.append("Total pot %s %s | Rake $0" % (_m(total), " ".join(parts)))
    else:
        L.append("Total pot %s | Rake $0" % _m(total))
    if rec["board"]:
        L.append("Board [%s]" % cards_str(rec["board"]))
    collected = {int(k): v for k, v in rec["collected"].items()}
    pos_label = {"BTN": " (button)", "SB": " (small blind)", "BB": " (big blind)"}
    for s in sorted(seats):
        st = seats[s]
        lab = pos_label.get(st["position"], "")
        head = "Seat %d: %s%s" % (s, st["name"], lab)
        if s in folded_on:
            fs = folded_on[s]
            if fs == "preflop":
                vol = any(a["seat"] == s and a["type"] in ("call", "raise") for a in acts)
                blind = st["position"] in ("SB", "BB")
                L.append("%s folded before Flop%s" % (head, "" if (vol or blind) else " (didn't bet)"))
            else:
                L.append("%s folded on the %s" % (head, STREET_TITLE.get(fs, fs.title())))
        elif rec["showdown"] and str(s) in rec["descriptions"]:
            desc = rec["descriptions"][str(s)]
            if collected.get(s):
                L.append("%s showed [%s] and won (%s) with %s" % (head, cards_str(st["hole"]), _m(collected[s]), desc))
            else:
                L.append("%s showed [%s] and lost with %s" % (head, cards_str(st["hole"]), desc))
        elif collected.get(s):
            L.append("%s collected (%s)" % (head, _m(collected[s])))
    return "\n".join(L) + "\n"
