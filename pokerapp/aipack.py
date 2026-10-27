"""Build a zip with everything an AI (Claude or an agent) needs to analyze your play and find leaks."""
import csv
import io
import json
import zipfile
from datetime import datetime

from .analysis import aggregate
from .bots import ARCHETYPE_LABEL
from .cards import card_str

REFS = {"vpip": "22-28%", "pfr": "18-24%", "three_bet": "6-10%", "af": "2-4", "wtsd": "25-31%",
        "wsd": "50-56%", "cbet": "50-70%", "fold_to_cbet": "35-50%"}
LABELS = {"vpip": "VPIP (voluntarily put $ in pot)", "pfr": "PFR (preflop raise)", "three_bet": "3-bet",
          "af": "AF (aggression factor, postflop bets+raises / calls)", "wtsd": "WTSD (went to showdown, of flops seen)",
          "wsd": "W$SD (won $ at showdown)", "cbet": "C-bet (flop continuation bet)", "fold_to_cbet": "Fold to c-bet"}

PROMPT = """# Poker hand analysis pack

You are reviewing hands I played in **6-max No-Limit Hold'em cash games against bots** in a local app.
Everyone starts each table with 100 big blinds. Stakes: $1K table = $5/$10, $5K = $25/$50, $25K = $125/$250, $100K = $500/$1,000.
I am the player marked `is_hero` / named "{hero}".

## What I want from you
1. Read `summary.md` first (my stats vs. typical winning-player ranges, results by position and street).
2. Use `decisions.csv` to find patterns. Every row is one decision I made.
3. Use `costly_spots.md` for concrete examples, and `hands.json` / `hands_pokerstars.txt` if you need full detail.
4. Give me my **3-5 biggest leaks, ranked by how much money they likely cost**. For each:
   - the pattern, in one sentence
   - 2-3 example hand IDs
   - a simple, concrete rule to fix it
5. Then list 2-3 things I'm doing well, and one drill or focus for my next session.
Be concise and direct. Use plain language and expand poker acronyms the first time.

## Important notes on the data
- **equity_vs_ranges** = my share of the pot vs. the hands opponents *likely* held given their actions (the fair measure: what I could know).
- **equity_vs_actual** = vs. their real cards (hindsight; useful for luck, not for judging decisions).
- **equity_needed** = the pot odds I needed to call (to_call / (pot + to_call)).
- **flags** are automatic heuristics from the app (mistake / note / info). Treat them as hints, not truth.
- Opponents are bots of known types (see `bot_types` in summary.md). Exploiting their type matters.
- Equity vs ranges uses a simple range model, so it's approximate. Small differences (<5%) are noise.

## Files
- `summary.md`: stats, results by position / stakes / street-action, bot types
- `decisions.csv`: one row per decision (the main file for finding leaks)
- `costly_spots.md`: the decisions that likely cost the most, with full hand text and everyone's cards
- `hands.json`: every hand: all players' hole cards, bot types, every action, pots, my per-decision analysis
- `hands_pokerstars.txt`: standard PokerStars-format hand histories
"""


def _pct(v):
    return "-" if v is None else "%s%%" % v


def _cards(cs):
    return " ".join(card_str(c) for c in cs)


def _cost(d):
    """Rough $ cost of a flagged decision (positive = money lost vs the better option)."""
    if d["action"] == "fold" and d["to_call"]:
        return max(0.0, d["eq_range"] * (d["pot"] + d["to_call"]) - d["to_call"])
    if d["action"] == "call" and d["to_call"]:
        return max(0.0, d["to_call"] - d["eq_range"] * (d["pot"] + d["to_call"]))
    return 0.0


def build_pack(db, where, args, hero_name="Hero"):
    rows = db.hand_rows(where, args, cols="id, session_id, ts, stakes_id, bb, hero_pos, hero_cards, board, hero_net, "
                        "pot, showdown, ev_net, mistakes, notes, record, facts, analysis, hh")
    hands = []
    for r in rows:
        hands.append({
            "row": r, "record": json.loads(r["record"]), "facts": json.loads(r["facts"]),
            "analysis": json.loads(r["analysis"]) if r["analysis"] else None,
        })

    buf = io.BytesIO()
    z = zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED)
    z.writestr("README_FOR_AI.md", PROMPT.format(hero=hero_name))

    # ---------------- decisions.csv
    dbuf = io.StringIO()
    w = csv.writer(dbuf)
    w.writerow(["hand_id", "stakes", "big_blind", "position", "hole_cards", "street", "board", "action", "amount",
                "pot", "to_call", "equity_needed", "equity_vs_ranges", "equity_vs_actual", "opponents",
                "opponent_types", "flags", "app_suggestion", "hand_net_$", "hand_net_bb"])
    all_decs = []
    for h in hands:
        r, rec, an = h["row"], h["record"], h["analysis"]
        if not an:
            continue
        types = "; ".join("%s=%s" % (s["position"], s["archetype"]) for s in rec["seats"] if not s["is_hero"])
        for d in an["decisions"]:
            all_decs.append((h, d))
            w.writerow([r["id"], r["stakes_id"], r["bb"], r["hero_pos"], r["hero_cards"], d["street"], d["board"],
                        d["action"], d["amount"], d["pot"], d["to_call"], d["req"], d["eq_range"], d["eq_actual"],
                        d["opponents"], types, " | ".join("%s: %s" % (f["level"], f["text"]) for f in d["flags"]),
                        (d.get("should") or {}).get("label", ""), r["hero_net"], round(r["hero_net"] / r["bb"], 1)])
    z.writestr("decisions.csv", dbuf.getvalue())

    # ---------------- summary.md
    agg = aggregate([{"id": h["row"]["id"], "facts": h["facts"], "bb": h["row"]["bb"], "net": h["row"]["hero_net"],
                      "ev_net": h["row"]["ev_net"], "stakes_id": h["row"]["stakes_id"],
                      "mistakes": h["row"]["mistakes"], "showdown_hero": h["row"]["showdown"]} for h in hands])
    o = agg["overall"]
    L = ["# Summary", "", "Generated %s. Hands: %d. Net: $%s (%s bb/100). All-in-luck-adjusted net: $%s."
         % (datetime.now().strftime("%Y-%m-%d %H:%M"), o["hands"], "{:,}".format(o["net"]), o["bb100"],
            "{:,.0f}".format(agg["series"][-1][2]) if agg["series"] else "0"), ""]
    L += ["## My stats vs. typical solid 6-max regular", "", "| Stat | Me | Typical |", "|---|---|---|"]
    for k in ["vpip", "pfr", "three_bet", "af", "wtsd", "wsd", "cbet", "fold_to_cbet"]:
        v = o.get(k)
        L.append("| %s | %s | %s |" % (LABELS[k], (v if k == "af" else _pct(v)) if v is not None else "-", REFS[k]))
    L += ["", "Auto-flagged mistakes: %d" % o["mistakes"], ""]
    L += ["## By position", "", "| Pos | Hands | Net $ | bb/100 | VPIP | PFR | WTSD |", "|---|---|---|---|---|---|---|"]
    for p, b in agg["by_position"].items():
        L.append("| %s | %d | %s | %s | %s | %s | %s |" % (p, b["hands"], "{:,}".format(b["net"]), b["bb100"],
                                                           _pct(b["vpip"]), _pct(b["pfr"]), _pct(b["wtsd"])))
    L += ["", "## By stakes", "", "| Stakes | Hands | Net $ | bb/100 |", "|---|---|---|---|"]
    for k, b in agg["by_stakes"].items():
        L.append("| $%s | %d | %s | %s |" % (k.upper(), b["hands"], "{:,}".format(b["net"]), b["bb100"]))
    # street x action table
    grp = {}
    for h, d in all_decs:
        key = (d["street"], d["action"])
        g = grp.setdefault(key, {"n": 0, "eq": 0.0, "req": 0.0, "faced": 0, "mist": 0, "notes": 0})
        g["n"] += 1
        g["eq"] += d["eq_range"]
        if d["to_call"]:
            g["faced"] += 1
            g["req"] += d["req"]
        g["mist"] += sum(1 for f in d["flags"] if f["level"] == "mistake")
        g["notes"] += sum(1 for f in d["flags"] if f["level"] == "note")
    L += ["", "## Decisions by street and action", "",
          "| Street | Action | Count | Avg equity vs ranges | Avg equity needed (when facing a bet) | Mistakes | Notes |",
          "|---|---|---|---|---|---|---|"]
    order = {"preflop": 0, "flop": 1, "turn": 2, "river": 3}
    for (st, act), g in sorted(grp.items(), key=lambda x: (order.get(x[0][0], 9), x[0][1])):
        L.append("| %s | %s | %d | %d%% | %s | %d | %d |" % (
            st, act, g["n"], round(100 * g["eq"] / g["n"]),
            ("%d%%" % round(100 * g["req"] / g["faced"])) if g["faced"] else "-", g["mist"], g["notes"]))
    # opponents
    seen = {}
    for h in hands:
        for s in h["record"]["seats"]:
            if not s["is_hero"] and s["archetype"]:
                seen[s["archetype"]] = seen.get(s["archetype"], 0) + 1
    L += ["", "## bot_types (seat-hands played against each type)", ""]
    for k, n in sorted(seen.items(), key=lambda x: -x[1]):
        L.append("- **%s** (%s): %d" % (k, ARCHETYPE_LABEL.get(k, k), n))
    z.writestr("summary.md", "\n".join(L) + "\n")

    # ---------------- costly_spots.md
    flagged = [(h, d) for h, d in all_decs if any(f["level"] in ("mistake", "note") for f in d["flags"])]
    flagged.sort(key=lambda x: -_cost(x[1]))
    biggest_losses = sorted(hands, key=lambda h: h["row"]["hero_net"] / h["row"]["bb"])[:10]
    C = ["# Costly spots", "",
         "Top flagged decisions by rough $ cost (forgone call EV on folds, or overpaid on calls), "
         "followed by my 10 biggest losing hands. All players' hole cards are shown.", ""]

    def hand_block(h, d=None):
        rec, r = h["record"], h["row"]
        out = ["### Hand #%d · $%s/$%s · I'm %s with %s · net %+d ($) / %+.1f bb"
               % (r["id"], rec["sb"], rec["bb"], r["hero_pos"], r["hero_cards"], r["hero_net"], r["hero_net"] / r["bb"])]
        if d:
            out.append("**Decision:** %s %s · pot $%s · to call $%s · needed %d%% · equity vs ranges %d%% · vs actual %d%% · est. cost ~$%d"
                       % (d["street"], d["action"], d["pot"], d["to_call"], round(100 * d["req"]),
                          round(100 * d["eq_range"]), round(100 * d["eq_actual"]), round(_cost(d))))
            for f in d["flags"]:
                out.append("- %s: %s" % (f["level"], f["text"]))
        out.append("Players: " + "; ".join("%s %s [%s] %s" % (s["position"], s["name"], _cards(s["hole"]),
                                                               ("(me)" if s["is_hero"] else "(%s)" % s["archetype"]))
                                         for s in rec["seats"]))
        out += ["```", r["hh"].rstrip(), "```", ""]
        return out

    done = set()
    C.append("## Top flagged decisions")
    C.append("")
    for h, d in flagged[:20]:
        C += hand_block(h, d)
        done.add(h["row"]["id"])
    C.append("## Biggest losing hands")
    C.append("")
    for h in biggest_losses:
        if h["row"]["id"] in done or h["row"]["hero_net"] >= 0:
            continue
        C += hand_block(h)
    z.writestr("costly_spots.md", "\n".join(C) + "\n")

    # ---------------- full data
    z.writestr("hands.json", json.dumps([{
        "id": h["row"]["id"], "record": h["record"], "facts": h["facts"], "analysis": h["analysis"]} for h in hands]))
    z.writestr("hands_pokerstars.txt", "\n\n\n".join(h["row"]["hh"].rstrip() for h in hands) + "\n")
    z.close()
    return buf.getvalue()
