"""No-limit Hold'em hand engine: blinds, betting, min-raise rules, side pots, showdown."""
import random

from .cards import evaluate, describe

STREETS = ["preflop", "flop", "turn", "river"]
POSITION_NAMES = {
    10: ["BTN", "SB", "BB", "UTG", "UTG+1", "UTG+2", "MP", "LJ", "HJ", "CO"],
    9: ["BTN", "SB", "BB", "UTG", "UTG+1", "MP", "LJ", "HJ", "CO"],
    8: ["BTN", "SB", "BB", "UTG", "UTG+1", "LJ", "HJ", "CO"],
    7: ["BTN", "SB", "BB", "UTG", "LJ", "HJ", "CO"],
    6: ["BTN", "SB", "BB", "UTG", "HJ", "CO"],
    5: ["BTN", "SB", "BB", "HJ", "CO"],
    4: ["BTN", "SB", "BB", "CO"],
    3: ["BTN", "SB", "BB"],
    2: ["BTN", "BB"],
}


class Player:
    def __init__(self, seat, name, stack, is_hero=False, profile=None):
        self.seat = seat          # 1..6
        self.name = name
        self.stack = stack
        self.is_hero = is_hero
        self.profile = profile    # bot Profile, None for hero
        self.reset()

    def reset(self):
        self.hole = []
        self.folded = False
        self.all_in = False
        self.street_bet = 0
        self.total_bet = 0
        self.start_stack = self.stack


class Hand:
    def __init__(self, hand_id, players, button_seat, sb, bb, rng=None):
        self.id = hand_id
        self.players = sorted(players, key=lambda p: p.seat)
        for p in self.players:
            p.reset()
        self.n = len(self.players)
        self.sb, self.bb = sb, bb
        self.rng = rng or random.Random()
        self.button_idx = next(i for i, p in enumerate(self.players) if p.seat == button_seat)
        self.button_seat = button_seat
        self.deck = list(range(52))
        self.rng.shuffle(self.deck)
        self.board = []
        self.street = "preflop"
        self.actions = []        # structured action log
        self.done = False
        self.showdown = False
        self.pots = []
        self.collected = {}
        self.uncalled = []
        self.current_bet = 0
        self.last_raise = bb
        self.need = set()
        self.can_raise = {}
        self.to_act = None
        names = POSITION_NAMES.get(self.n, POSITION_NAMES[6])
        self.positions = {}
        for k in range(self.n):
            p = self.players[(self.button_idx + k) % self.n]
            self.positions[p.seat] = names[k] if k < len(names) else "MP"

    # ---------- helpers ----------
    def idx(self, p):
        return self.players.index(p)

    def by_seat(self, seat):
        for p in self.players:
            if p.seat == seat:
                return p
        return None

    def live(self):
        return [p for p in self.players if not p.folded]

    def pot_total(self):
        return sum(p.total_bet for p in self.players)

    def actor(self):
        return None if self.to_act is None else self.players[self.to_act]

    def _next_needing(self, from_idx):
        for k in range(1, self.n + 1):
            i = (from_idx + k) % self.n
            if i in self.need:
                return i
        return None

    def _log(self, p, typ, amount=0, to=None, raise_by=None, extra=None):
        e = {
            "i": len(self.actions), "street": self.street, "seat": p.seat if p else None,
            "type": typ, "amount": amount, "to": to, "raise_by": raise_by,
            "allin": bool(p and p.all_in and typ in ("call", "bet", "raise", "post_sb", "post_bb")),
            "board_len": len(self.board),
        }
        if extra:
            e.update(extra)
        self.actions.append(e)
        return e

    def _put(self, p, amt):
        amt = min(amt, p.stack)
        p.stack -= amt
        p.street_bet += amt
        p.total_bet += amt
        if p.stack == 0:
            p.all_in = True
        return amt

    # ---------- flow ----------
    def start(self):
        for _ in range(2):
            for k in range(1, self.n + 1):
                self.players[(self.button_idx + k) % self.n].hole.append(self.deck.pop())
        if self.n == 2:
            sb_i, bb_i = self.button_idx, (self.button_idx + 1) % self.n
        else:
            sb_i, bb_i = (self.button_idx + 1) % self.n, (self.button_idx + 2) % self.n
        p = self.players[sb_i]
        a = self._put(p, self.sb)
        self._log(p, "post_sb", a, to=a)
        p = self.players[bb_i]
        a = self._put(p, self.bb)
        self._log(p, "post_bb", a, to=a)
        self.current_bet = self.bb
        self.last_raise = self.bb
        self.need = {i for i, q in enumerate(self.players) if not q.all_in}
        self.can_raise = {i: True for i in range(self.n)}
        self.to_act = self._next_needing(bb_i)
        self._check_round_end()

    def legal(self, p=None):
        p = p or self.actor()
        i = self.idx(p)
        to_call = min(self.current_bet - p.street_bet, p.stack)
        others_can_act = any(not q.folded and not q.all_in and q is not p for q in self.players)
        max_to = p.street_bet + p.stack
        min_to = min(self.current_bet + self.last_raise if self.current_bet else self.bb, max_to)
        can_raise = (self.can_raise.get(i, True) and p.stack > to_call and others_can_act
                     and max_to > self.current_bet)
        return {
            "to_call": to_call,
            "can_check": to_call == 0,
            "can_call": to_call > 0,
            "can_raise": can_raise,
            "raise_word": "bet" if self.current_bet == 0 else "raise",
            "min_to": min_to,
            "max_to": max_to,
            "pot": self.pot_total(),
            "current_bet": self.current_bet,
            "street_bet": p.street_bet,
        }

    def apply(self, action, amount_to=None):
        """Apply action for the current actor. action in fold/check/call/bet/raise."""
        p = self.actor()
        if p is None or self.done:
            raise ValueError("no player to act")
        i = self.idx(p)
        L = self.legal(p)
        snap = {"pot_before": L["pot"], "to_call": L["to_call"], "stack_before": p.stack,
                "current_bet_before": self.current_bet}
        if action == "check" and not L["can_check"]:
            action = "call"
        if action == "call" and L["to_call"] == 0:
            action = "check"
        if action in ("bet", "raise") and not L["can_raise"]:
            action = "call" if L["to_call"] > 0 else "check"
        if action == "fold" and L["to_call"] == 0:
            action = "check"

        if action == "fold":
            p.folded = True
            self._log(p, "fold", extra=snap)
        elif action == "check":
            self._log(p, "check", extra=snap)
        elif action == "call":
            a = self._put(p, L["to_call"])
            snap["put"] = a
            self._log(p, "call", a, to=p.street_bet, extra=snap)
        else:
            to = int(amount_to if amount_to is not None else L["min_to"])
            to = max(L["min_to"], min(to, L["max_to"]))
            prev = self.current_bet
            snap["put"] = self._put(p, to - p.street_bet)
            raise_by = to - prev
            typ = "bet" if prev == 0 else "raise"
            self._log(p, typ, raise_by if typ == "raise" else to, to=to, raise_by=raise_by, extra=snap)
            if raise_by >= self.last_raise:
                self.last_raise = raise_by
                for j in range(self.n):
                    if j != i:
                        self.can_raise[j] = True
            self.current_bet = max(self.current_bet, to)
            self.need = {j for j, q in enumerate(self.players)
                         if j != i and not q.folded and not q.all_in}
        self.can_raise[i] = False
        self.need.discard(i)
        self.to_act = self._next_needing(i)
        self._check_round_end()

    def _check_round_end(self):
        while not self.done:
            live = self.live()
            if len(live) == 1:
                self._return_uncalled()
                self._award_uncontested(live[0])
                return
            if self.need and self.to_act is not None:
                # a lone player who can act but faces no bet doesn't need to act
                actors = [q for q in live if not q.all_in]
                if len(actors) == 1 and actors[0].street_bet >= self.current_bet:
                    self.need.clear()
                else:
                    return
            # betting round over
            self._return_uncalled()
            if self.street == "river":
                self._showdown()
                return
            self._next_street()

    def _return_uncalled(self):
        bets = sorted(self.players, key=lambda q: -q.street_bet)
        if len(bets) < 2:
            return
        top, second = bets[0], bets[1]
        diff = top.street_bet - second.street_bet
        if diff > 0:
            top.street_bet -= diff
            top.total_bet -= diff
            top.stack += diff
            if top.stack > 0:
                top.all_in = False
            self.uncalled.append({"seat": top.seat, "amount": diff, "street": self.street})
            self._log(top, "uncalled", diff)

    def _next_street(self):
        nxt = STREETS[STREETS.index(self.street) + 1]
        self.street = nxt
        self.deck.pop()  # burn
        if nxt == "flop":
            self.board += [self.deck.pop() for _ in range(3)]
        else:
            self.board.append(self.deck.pop())
        self._log(None, "deal", extra={"board": list(self.board)})
        for q in self.players:
            q.street_bet = 0
        self.current_bet = 0
        self.last_raise = self.bb
        self.can_raise = {i: True for i in range(self.n)}
        actors = [i for i, q in enumerate(self.players) if not q.folded and not q.all_in]
        if len(actors) >= 2:
            self.need = set(actors)
            self.to_act = self._next_needing(self.button_idx)
        else:
            self.need = set()
            self.to_act = None

    def _build_pots(self):
        remaining = {p.seat: p.total_bet for p in self.players if p.total_bet > 0}
        live_seats = {p.seat for p in self.live()}
        pots = []
        while any(v > 0 for v in remaining.values()):
            elig = [s for s in remaining if remaining[s] > 0 and s in live_seats]
            if not elig:
                amt = sum(remaining.values())
                if pots:
                    pots[-1]["amount"] += amt
                for s in remaining:
                    remaining[s] = 0
                break
            level = min(remaining[s] for s in elig)
            amt = 0
            for s in remaining:
                take = min(remaining[s], level)
                remaining[s] -= take
                amt += take
            if pots and set(pots[-1]["eligible"]) == set(elig):
                pots[-1]["amount"] += amt
            else:
                pots.append({"amount": amt, "eligible": sorted(elig)})
        return pots

    def _order_from_button(self, seats):
        order = [self.players[(self.button_idx + k) % self.n].seat for k in range(1, self.n + 1)]
        return [s for s in order if s in seats]

    def _award_uncontested(self, p):
        amt = self.pot_total()
        self.pots = [{"amount": amt, "eligible": [p.seat], "winners": [p.seat]}]
        p.stack += amt
        self.collected = {p.seat: amt}
        self._log(p, "collect", amt, extra={"pot_index": 0, "npots": 1})
        self._finish()

    def award_pots(self, board, holes, pots):
        """Return {seat: amount} for given full board and hole cards (used by analysis too)."""
        scores = {s: evaluate(holes[s] + board) for s in holes}
        won = {}
        for pot in pots:
            best = max(scores[s] for s in pot["eligible"])
            winners = self._order_from_button([s for s in pot["eligible"] if scores[s] == best])
            share, odd = divmod(pot["amount"], len(winners))
            for k, s in enumerate(winners):
                won[s] = won.get(s, 0) + share + (1 if k < odd else 0)
        return won

    def _showdown(self):
        self.showdown = True
        self.street = "showdown"
        live = self.live()
        self.scores = {p.seat: evaluate(p.hole + self.board) for p in live}
        self.descriptions = {s: describe(v) for s, v in self.scores.items()}
        pots = self._build_pots()
        for k, pot in enumerate(pots):
            best = max(self.scores[s] for s in pot["eligible"])
            winners = self._order_from_button([s for s in pot["eligible"] if self.scores[s] == best])
            pot["winners"] = winners
            share, odd = divmod(pot["amount"], len(winners))
            for j, s in enumerate(winners):
                amt = share + (1 if j < odd else 0)
                self.by_seat(s).stack += amt
                self.collected[s] = self.collected.get(s, 0) + amt
                self._log(self.by_seat(s), "collect", amt, extra={"pot_index": k, "npots": len(pots)})
        self.pots = pots
        self._finish()

    def _finish(self):
        self.done = True
        self.to_act = None
        self.need = set()
