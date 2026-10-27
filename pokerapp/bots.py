"""Bot players: preflop ranges by position + postflop Monte Carlo equity vs modeled ranges.

Archetypes range from 'fish' (loose, passive, plays hand strength vs random hands)
to 'shark' (positional ranges, range-narrowing, adapts to observed opponent tendencies).
These are strong heuristic bots, not a game-theory solver.
"""
import random

from .ranges import (open_pct, call_pct, BASE_3BET, BASE_4BET, hand_pct,
                     estimate_range, equity_vs_ranges, has_draw)

ARCHETYPES = {
    #            open  call  3bet  4bet  limp  cbet  bluff aggr  slack noise  samples model     adapt
    "fish":    (1.9,  2.4,  0.5,  0.5,  0.65, 0.35, 0.08, 0.35, 0.10, 0.10, 120, "none",    False),
    "station": (1.6,  3.0,  0.3,  0.4,  0.50, 0.30, 0.04, 0.20, 0.20, 0.08, 120, "none",    False),
    "maniac":  (2.6,  1.8,  3.2,  2.0,  0.00, 0.85, 0.45, 0.90, 0.06, 0.08, 150, "preflop", False),
    "nit":     (0.6,  0.6,  0.5,  0.6,  0.10, 0.50, 0.04, 0.45,-0.04, 0.04, 250, "full",    False),
    "tag":     (1.0,  1.0,  1.0,  1.0,  0.00, 0.62, 0.18, 0.60, 0.00, 0.03, 300, "full",    True),
    "lag":     (1.35, 1.2,  1.7,  1.4,  0.00, 0.70, 0.28, 0.75, 0.01, 0.03, 300, "full",    True),
    "shark":   (1.0,  1.0,  1.1,  1.0,  0.00, 0.62, 0.22, 0.66,-0.01, 0.012, 450, "full",   True),
}

ARCHETYPE_LABEL = {
    "fish": "Fish (loose-passive)", "station": "Calling station", "maniac": "Maniac (hyper-aggressive)",
    "nit": "Nit (very tight)", "tag": "TAG (tight-aggressive reg)", "lag": "LAG (loose-aggressive reg)",
    "shark": "Shark (strongest bot)",
}

TIER_WEIGHTS = {
    "1k":   {"fish": 30, "station": 20, "maniac": 14, "nit": 14, "tag": 16, "lag": 5, "shark": 1},
    "5k":   {"fish": 14, "station": 9, "maniac": 9, "nit": 14, "tag": 30, "lag": 16, "shark": 8},
    "25k":  {"fish": 4, "station": 2, "maniac": 4, "nit": 10, "tag": 34, "lag": 24, "shark": 22},
    "100k": {"tag": 22, "lag": 28, "shark": 50},
}

NAMES = ["Ace_Ventura", "BigSlick88", "RiverRat", "TiltedTony", "Vegas_Vic", "LuckyLou", "CheckRaiseCarl",
         "NutPeddler", "DonkeyKong", "SharkBait", "FoldEquity", "Gutshot_Gus", "PocketRockets", "SnapCall",
         "Bellagio_Bob", "Felt_Fiend", "OverbetOlga", "SlowRollSam", "MinRaiseMo", "TripleBarrel", "ColdDeck",
         "Wynn_Some", "QuadQueen", "BubbleBoy", "ShipIt_Sheila", "DealerDan", "NeonNina", "SuitedSue",
         "Kicker_Kev", "TheRock", "ValueTown", "BlockerBet", "HighRoller_H", "LowBallLarry", "Boomer_B",
         "ScaredMoney", "Wheel_Wanda", "BoatDrawer", "Mucker_Mike", "RailBird", "CoolerCody", "FlopZilla",
         "TurnTiger", "NitNick", "LAGgy_Lee", "RunGood_Rae", "Variance_V", "TankTime", "StackSnatcher"]


class Profile:
    def __init__(self, archetype):
        self.archetype = archetype
        (self.open_mult, self.call_mult, self.tb_mult, self.fb_mult, self.limp, self.cbet,
         self.bluff, self.aggr, self.slack, self.noise, self.samples, self.model,
         self.adapt) = ARCHETYPES[archetype]

    @property
    def label(self):
        return ARCHETYPE_LABEL[self.archetype]


def random_profile(tier, rng):
    w = TIER_WEIGHTS[tier]
    kinds = list(w)
    return Profile(rng.choices(kinds, weights=[w[k] for k in kinds])[0])


def hand_view(hand):
    return {"positions": hand.positions, "actions": hand.actions, "board": hand.board, "bb": hand.bb}


def _round_amt(x, hand):
    unit = hand.sb if hand.sb >= 1 else 1
    return int(max(unit, round(x / unit) * unit))


class Bot:
    def __init__(self, profile, rng=None):
        self.p = profile
        self.rng = rng or random.Random()

    # ------------------------------------------------------------ entry
    def decide(self, hand, me, observed):
        L = hand.legal(me)
        if hand.street == "preflop":
            act, to = self._preflop(hand, me, L, observed)
        else:
            act, to = self._postflop(hand, me, L, observed)
        if act in ("bet", "raise"):
            if not L["can_raise"]:
                act = "call" if L["to_call"] else "check"
            else:
                to = max(L["min_to"], min(int(to), L["max_to"]))
                if to >= 0.72 * L["max_to"]:
                    to = L["max_to"]
        if act == "fold" and L["to_call"] == 0:
            act = "check"
        return act, to

    # ------------------------------------------------------------ preflop
    def _preflop_ctx(self, hand, me):
        raises = 0
        limpers = 0
        last_raiser = None
        callers_since = 0
        for a in hand.actions:
            if a["street"] != "preflop":
                break
            t = a["type"]
            if t == "raise":
                raises += 1
                last_raiser = a["seat"]
                callers_since = 0
            elif t == "call":
                if raises == 0:
                    limpers += 1
                else:
                    callers_since += 1
        return raises, limpers, last_raiser, callers_since

    def _preflop(self, hand, me, L, observed):
        P, r = self.p, self.rng.random()
        pct = hand_pct(me.hole)
        pos = hand.positions[me.seat]
        bb = hand.bb
        raises, limpers, last_raiser, callers = self._preflop_ctx(hand, me)
        to_call = L["to_call"]
        eff_bb = (me.stack + me.street_bet) / bb

        # short stack: push/fold
        if eff_bb <= 14:
            jam_range = min(0.6, (0.10 + 0.9 / max(eff_bb, 1.5)) * (P.open_mult ** 0.5))
            if raises >= 1:
                jam_range *= 0.45
            if pct < jam_range:
                return "raise", L["max_to"]
            return ("check", 0) if L["can_check"] else ("fold", 0)

        if raises == 0:
            open_r = min(0.95, open_pct(pos, hand.n) * P.open_mult)
            if limpers:
                open_r *= 0.65
            if pos == "BB":
                if pct < 0.09 * P.open_mult * (1.4 if limpers else 1):
                    return "raise", _round_amt(bb * (3.5 + limpers), hand)
                return "check", 0
            if pct < open_r:
                if P.limp and r < P.limp and pct > 0.04:
                    return "call", 0
                size = 3.0 if pos == "SB" else 2.5
                if P.archetype == "maniac":
                    size += self.rng.choice([0.5, 1, 1.5])
                return "raise", _round_amt(bb * (size + limpers), hand)
            if P.limp and pct < min(0.75, open_r * 1.6) and r < P.limp:
                return "call", 0
            if pos == "SB" and pct < 0.55 and P.limp:
                return "call", 0
            return "fold", 0

        raiser_pos = hand.positions.get(last_raiser, "MP")
        size_bb = hand.current_bet / bb
        loose = self._looseness(hand, last_raiser, observed)

        if raises == 1:
            late = raiser_pos in ("CO", "BTN", "SB")
            tb = BASE_3BET * P.tb_mult * (1.5 if late else 1.0) * min(1.6, loose)
            call_r = call_pct(pos, hand.n) * P.call_mult * min(1.5, loose ** 0.5)
            call_r *= min(1.0, 3.0 / max(size_bb, 2.0)) ** 0.8
            if callers:
                call_r *= 1.15
            if pct < tb:
                ip = pos not in ("SB", "BB")
                mult = (3.0 if ip else 3.8) + callers
                return "raise", _round_amt(hand.current_bet * mult, hand)
            if pct < call_r:
                return "call", 0
            # light 3-bet bluffs with hands just outside calling range
            if call_r <= pct < call_r + 0.08 and r < 0.10 * P.tb_mult and late:
                return "raise", _round_amt(hand.current_bet * 3.3, hand)
            return "fold", 0

        if raises == 2:
            fb = BASE_4BET * P.fb_mult * min(1.5, loose)
            call_r = 0.075 * P.call_mult * min(1.5, loose ** 0.5)
            if me.street_bet <= bb:  # cold facing 3-bet
                call_r *= 0.5
            if pct < fb:
                return "raise", _round_amt(hand.current_bet * 2.3, hand)
            pot_odds = to_call / (L["pot"] + to_call)
            if pct < call_r or (pot_odds < 0.25 and pct < call_r * 1.6):
                return "call", 0
            return "fold", 0

        # facing 4-bet or more
        jam = 0.013 * P.fb_mult * min(1.4, loose)
        call_r = 0.022 * P.call_mult * min(1.4, loose)
        if pct < jam:
            return "raise", L["max_to"]
        if pct < call_r:
            return "call", 0
        return "fold", 0

    def _looseness(self, hand, seat, observed):
        """How much wider than baseline an opponent plays, from observed VPIP."""
        if not self.p.adapt or seat is None:
            return 1.0
        o = observed.get(hand.by_seat(seat).name) if hand.by_seat(seat) else None
        if not o or o["hands"] < 12:
            return 1.0
        vpip = o["vpip"] / o["hands"]
        return max(0.6, min(2.5, vpip / 0.25))

    # ------------------------------------------------------------ postflop
    def _postflop(self, hand, me, L, observed):
        P, rng = self.p, self.rng
        opps = [q for q in hand.live() if q is not me]
        view = hand_view(hand)
        dead = set(me.hole) | set(hand.board)
        ranges = []
        for q in opps:
            if P.model == "none":
                ranges.append(estimate_range({"positions": {}, "actions": [], "board": hand.board, "bb": hand.bb},
                                             q.seat, dead, postflop=False))
            else:
                ranges.append(estimate_range(view, q.seat, dead, loose=self._looseness(hand, q.seat, observed),
                                             postflop=(P.model == "full")))
        E = equity_vs_ranges(me.hole, hand.board, ranges, samples=P.samples, rng=rng)
        E = max(0.0, min(1.0, E + rng.gauss(0, P.noise)))

        pot = L["pot"]
        to_call = L["to_call"]
        n = len(opps)
        street = hand.street
        draw = has_draw(me.hole, hand.board)
        u = rng.random()
        was_pfr = self._last_preflop_raiser(hand) == me.seat
        stack = me.stack
        spr = stack / max(pot, 1)

        fold_mult = 1.0
        if P.adapt and n == 1:
            o = observed.get(opps[0].name)
            if o and o["faced_bet"] >= 10:
                fold_mult = max(0.5, min(1.8, (o["folded_to_bet"] / o["faced_bet"]) / 0.45))

        if to_call == 0:
            value_t = 0.52 + 0.08 * (n - 1) + (0.06 if street == "river" else 0) - (P.aggr - 0.5) * 0.12
            if E > value_t:
                if E > 0.88 and street == "flop" and u < 0.15 * (1 - P.aggr):
                    return "check", 0
                frac = 0.75 if E > 0.78 else 0.55
                if street == "river" and E > 0.9:
                    frac = rng.choice([0.75, 1.0, 1.25]) if P.aggr > 0.5 else 0.7
                if P.archetype == "maniac":
                    frac += 0.3
                return "bet", _round_amt(pot * frac, hand)
            if was_pfr and street == "flop" and n <= 2 and u < P.cbet * (fold_mult if n == 1 else 0.8):
                return "bet", _round_amt(pot * rng.choice([0.33, 0.5]), hand)
            if draw and street != "river" and u < P.aggr * 0.45:
                return "bet", _round_amt(pot * 0.6, hand)
            if n == 1 and u < P.bluff * fold_mult * (0.6 if street == "river" else 0.35) and E < 0.35:
                return "bet", _round_amt(pot * (0.66 if street == "river" else 0.5), hand)
            return "check", 0

        req = to_call / (pot + to_call)
        implied = 0.05 if (draw and street != "river" and spr > 2) else 0.0
        raise_t = 0.74 + 0.06 * (n - 1) - (P.aggr - 0.5) * 0.12
        if street == "river":
            raise_t += 0.06
        if E > raise_t and L["can_raise"]:
            if u < 0.2 and street == "flop" and P.aggr < 0.7:
                return "call", 0  # sometimes slowplay
            return "raise", _round_amt(L["current_bet"] * 2.8 + (pot - L["current_bet"]) * 0.4, hand)
        if draw and street == "flop" and L["can_raise"] and u < P.aggr * 0.18 and spr > 1.5:
            return "raise", _round_amt(L["current_bet"] * 3.0, hand)
        if E + implied + P.slack >= req:
            return "call", 0
        if n == 1 and L["can_raise"] and street != "river" and u < P.bluff * 0.07:
            return "raise", _round_amt(L["current_bet"] * 2.7, hand)
        return "fold", 0

    @staticmethod
    def _last_preflop_raiser(hand):
        last = None
        for a in hand.actions:
            if a["street"] != "preflop":
                break
            if a["type"] == "raise":
                last = a["seat"]
        return last
