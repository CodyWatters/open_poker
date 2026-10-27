"""Table/session management: bankroll buy-ins, bot seating, hand loop, saving hands."""
import os
import queue
import random
import threading
from datetime import datetime, timezone

from .analysis import analyze, hand_facts
from .bots import Bot, NAMES, random_profile
from .cards import cards_str, card_str
from .db import DB, now
from .engine import Hand, Player
from .hh import to_pokerstars

STAKES = [
    {"id": "1k", "name": "Vegas $1K", "buyin": 1000, "sb": 5, "bb": 10,
     "blurb": "Soft table. Mostly recreational players."},
    {"id": "5k", "name": "Vegas $5K", "buyin": 5000, "sb": 25, "bb": 50,
     "blurb": "Mixed: some fish, more regulars."},
    {"id": "25k", "name": "Vegas $25K", "buyin": 25000, "sb": 125, "bb": 250,
     "blurb": "Tough: mostly solid regulars and sharks."},
    {"id": "100k", "name": "Vegas $100K", "buyin": 100000, "sb": 500, "bb": 1000,
     "blurb": "High roller: the strongest bots only."},
]
STAKES_BY_ID = {s["id"]: s for s in STAKES}
HERO_SEAT = 1


def _pos_sort(p):
    return p.seat


class Game:
    def __init__(self, data_dir, hero_name="Hero"):
        os.makedirs(os.path.join(data_dir, "hand_histories"), exist_ok=True)
        self.data_dir = data_dir
        self.db = DB(os.path.join(data_dir, "poker.db"))
        self.hero_name = self.db.get("hero_name", hero_name)
        self.lock = threading.RLock()
        self.rng = random.Random()
        self.table = None
        self.q = queue.Queue()
        self._recover_sessions()
        self.db.bankroll()
        threading.Thread(target=self._analyzer, daemon=True).start()
        for hid in self.db.unanalyzed():
            self.q.put(hid)

    # ------------------------------------------------------------ background analysis
    def _analyzer(self):
        while True:
            hid = self.q.get()
            try:
                row = self.db.hand(hid)
                if row and not row["analysis"]:
                    self.db.save_analysis(hid, analyze(row["record"]))
            except Exception as e:  # keep worker alive
                print("analysis error for hand %s: %r" % (hid, e))

    def _recover_sessions(self):
        """If the server stopped mid-session, cash out the last saved stack."""
        for s in self.db.open_sessions():
            stack = s["last_stack"] or 0
            self.db.close_session(s["id"], stack)
            if stack:
                self.db.change_bankroll(stack, "cashout", "Recovered session #%d" % s["id"])

    # ------------------------------------------------------------ lobby
    def lobby(self):
        b = self.db.bankroll()
        return {
            "bankroll": b,
            "hero_name": self.hero_name,
            "stakes": [dict(s, locked=b < s["buyin"]) for s in STAKES],
            "in_session": self.table is not None,
            "table_stack": self.table.hero.stack if self.table else None,
            "topups": self.db.get("topups", 0),
            "can_topup": self.total_chips() < self.TOPUP_BELOW,
            "sessions": self.db.sessions(25),
            "bankroll_log": self.db.q("SELECT id, ts, kind, amount, balance, note FROM bankroll_log ORDER BY id"),
        }

    TOPUP_BELOW = 200
    TOPUP_AMOUNT = 1000

    def total_chips(self):
        return self.db.bankroll() + (self.table.hero.stack if self.table else 0)

    def top_up(self):
        """Buy $1,000 more. Only allowed when total chips (bankroll + table stack) are under $200."""
        with self.lock:
            if self.total_chips() >= self.TOPUP_BELOW:
                raise ValueError("You can only buy more chips when you're under $200.")
            self.db.change_bankroll(self.TOPUP_AMOUNT, "topup", "Bought $1,000")
            self.db.set("topups", self.db.get("topups", 0) + 1)
            return self.lobby()

    def erase_all(self):
        """Erase everything (hands, sessions, stats, hand-history files) and start over at $1,000."""
        with self.lock:
            if self.table:
                self.leave()
            with self.db.lock:
                for t in ("hands", "sessions", "bankroll_log"):
                    self.db.conn.execute("DELETE FROM %s" % t)
                self.db.conn.execute("DELETE FROM settings WHERE key IN ('bankroll', 'resets', 'topups')")
                self.db.conn.commit()
            hh_dir = os.path.join(self.data_dir, "hand_histories")
            for f in os.listdir(hh_dir):
                try:
                    os.remove(os.path.join(hh_dir, f))
                except OSError:
                    pass
            self.db.bankroll()
            return self.lobby()

    def set_hero_name(self, name):
        name = "".join(ch for ch in name if ch.isalnum() or ch in "_-")[:20] or "Hero"
        self.hero_name = name
        self.db.set("hero_name", name)
        return self.lobby()

    # ------------------------------------------------------------ table lifecycle
    def join(self, stakes_id):
        with self.lock:
            if self.table:
                raise ValueError("Already seated. Leave your table first.")
            st = STAKES_BY_ID[stakes_id]
            if self.db.bankroll() < st["buyin"]:
                raise ValueError("Not enough bankroll for this table.")
            self.db.change_bankroll(-st["buyin"], "buyin", st["name"])
            count = self.db.q("SELECT COUNT(*) AS c FROM sessions WHERE stakes_id=?", (stakes_id,), one=True)["c"]
            table_name = "%s #%d" % (st["name"], count + 1)
            sid = self.db.open_session(st, table_name)
            self.table = Table(self, st, sid, table_name)
            return self.table.new_hand()

    def leave(self):
        with self.lock:
            t = self.table
            if not t:
                return self.lobby()
            frames = []
            if t.hand and not t.hand.done:
                if t.hand.actor() is t.hero:
                    t.hand.apply("fold")
                    frames.append(t.frame("You fold and leave the table."))
                frames += t.run_bots()
            cash = t.hero.stack
            self.db.close_session(t.sid, cash)
            if cash:
                self.db.change_bankroll(cash, "cashout", t.table_name)
            self.table = None
            out = self.lobby()
            out["left_with"] = cash
            out["net"] = cash - t.stakes["buyin"]
            return out

    def state(self):
        with self.lock:
            if not self.table:
                return {"seated": False}
            return {"seated": True, "frames": [self.table.frame(None)]}

    def act(self, action, amount=None):
        with self.lock:
            if not self.table:
                raise ValueError("Not seated.")
            return self.table.hero_act(action, amount)

    def next_hand(self):
        with self.lock:
            if not self.table:
                raise ValueError("Not seated.")
            return self.table.new_hand()


class Table:
    def __init__(self, game, stakes, sid, table_name):
        self.game = game
        self.db = game.db
        self.stakes = stakes
        self.sid = sid
        self.table_name = table_name
        self.rng = random.Random()
        self.hero = Player(HERO_SEAT, game.hero_name, stakes["buyin"], is_hero=True)
        self.players = [self.hero]
        self.bots = {}
        for seat in range(1, 7):
            if seat != HERO_SEAT:
                self._seat_bot(seat)
        self.button = self.rng.randint(1, 6)
        self.hand = None
        self.observed = {}
        self.hands_played = 0
        self.session_start = stakes["buyin"]
        self.busted = False
        self.last_record = None

    def _seat_bot(self, seat):
        used = {p.name for p in self.players}
        name = self.rng.choice([n for n in NAMES if n not in used])
        prof = random_profile(self.stakes["id"], self.rng)
        p = Player(seat, name, self.stakes["buyin"], profile=prof)
        self.players = [q for q in self.players if q.seat != seat] + [p]
        self.players.sort(key=_pos_sort)
        self.bots[seat] = Bot(prof, random.Random(self.rng.random()))
        return p

    # ------------------------------------------------------------ frames for the UI
    def frame(self, msg, reveal=False):
        h = self.hand
        seats = []
        for p in self.players:
            show = p.is_hero or reveal or (h and h.done and h.showdown and not p.folded)
            last = None
            if h:
                for a in reversed(h.actions):
                    if a["seat"] == p.seat and a["type"] in ("fold", "check", "call", "bet", "raise", "post_sb", "post_bb"):
                        if a["street"] == h.street or a["type"] == "fold" or h.street == "showdown":
                            last = a["type"]
                        break
            seats.append({
                "seat": p.seat, "name": p.name, "stack": p.stack, "is_hero": p.is_hero,
                "bet": p.street_bet if h and not h.done else 0,
                "folded": p.folded if h else False, "all_in": p.all_in if h else False,
                "in_hand": bool(h and p.hole),
                "hole": [card_str(c) for c in p.hole] if (show and h) else None,
                "position": h.positions.get(p.seat) if h else None,
                "last": last,
                "won": (h.collected.get(p.seat, 0) if h and h.done else 0),
                "desc": (h.descriptions.get(p.seat) if h and h.done and h.showdown and not p.folded else None),
            })
        out = {
            "table_name": self.table_name, "stakes": self.stakes, "session_id": self.sid,
            "hand_id": h.id if h else None, "button": self.button,
            "street": h.street if h else None,
            "board": [card_str(c) for c in h.board] if h else [],
            "pot": h.pot_total() if h else 0,
            "seats": seats, "msg": msg,
            "hand_over": bool(h and h.done), "busted": self.busted,
            "to_act": h.actor().seat if (h and not h.done and h.actor()) else None,
            "session": {"buyin": self.session_start, "stack": self.hero.stack,
                        "net": self.hero.stack - self.session_start, "hands": self.hands_played},
        }
        if h and not h.done and h.actor() is self.hero:
            out["legal"] = h.legal(self.hero)
        if h and h.done:
            out["result"] = {"hero_net": self.hero.stack - self.hero.start_stack,
                             "showdown": h.showdown}
        return out

    def _describe(self, a):
        p = self.hand.by_seat(a["seat"]) if a["seat"] else None
        t = a["type"]
        n = p.name if p else ""
        ai = " (all-in)" if a.get("allin") else ""
        if t == "fold":
            return "%s folds" % n
        if t == "check":
            return "%s checks" % n
        if t == "call":
            return "%s calls $%s%s" % (n, "{:,}".format(a["amount"]), ai)
        if t == "bet":
            return "%s bets $%s%s" % (n, "{:,}".format(a["to"]), ai)
        if t == "raise":
            return "%s raises to $%s%s" % (n, "{:,}".format(a["to"]), ai)
        if t == "deal":
            return "%s: %s" % (self.hand.street.title() if self.hand.street != "showdown" else "Board",
                               cards_str(a["board"]))
        if t == "uncalled":
            return "$%s returned to %s" % ("{:,}".format(a["amount"]), n)
        if t == "collect":
            d = self.hand.descriptions.get(a["seat"]) if self.hand.showdown else None
            return "%s wins $%s%s" % (n, "{:,}".format(a["amount"]), (" with " + d) if d else "")
        if t == "post_sb":
            return "%s posts SB $%s" % (n, a["amount"])
        if t == "post_bb":
            return "%s posts BB $%s" % (n, a["amount"])
        return t

    def _frames_since(self, start):
        """One frame per new action (state is captured after all actions; UI animates text)."""
        out = []
        for a in self.hand.actions[start:]:
            out.append(self._describe(a))
        return out

    # ------------------------------------------------------------ hand loop
    def new_hand(self):
        if self.hand and not self.hand.done:
            return [self.frame(None)]
        if self.hero.stack <= 0:
            self.busted = True
            return [self.frame("You're out of chips.")]
        for p in list(self.players):
            if not p.is_hero and p.stack <= 0:
                self._seat_bot(p.seat)
        seats = sorted(p.seat for p in self.players)
        nxt = [s for s in seats if s > self.button]
        self.button = nxt[0] if nxt else seats[0]
        hid = self.db.next_hand_id()
        self.hand = Hand(hid, self.players, self.button, self.stakes["sb"], self.stakes["bb"], self.rng)
        self.hand.descriptions = {}
        self.hand.start()
        frames = [self.frame("New hand #%d" % hid)]
        frames += self.run_bots(start=0)
        return frames

    def run_bots(self, start=None):
        h = self.hand
        frames = []
        if start is not None and start == 0:
            # describe blinds without separate states
            pass
        while not h.done and h.actor() is not self.hero:
            p = h.actor()
            n0 = len(h.actions)
            act, to = self.bots[p.seat].decide(h, p, self.observed)
            h.apply(act, to)
            frames.append(self._step_frame(n0))
        if h.done and not getattr(h, "_saved", False):
            self._finish_hand()
            frames.append(self.frame(None))
        return frames

    def _step_frame(self, n0):
        texts = self._frames_since(n0)
        f = self.frame(" · ".join(texts))
        f["log"] = texts
        return f

    def hero_act(self, action, amount=None):
        h = self.hand
        if not h or h.done or h.actor() is not self.hero:
            return [self.frame(None)]
        n0 = len(h.actions)
        h.apply(action, amount)
        frames = [self._step_frame(n0)]
        frames += self.run_bots()
        return frames

    # ------------------------------------------------------------ saving
    def _finish_hand(self):
        h = self.hand
        h._saved = True
        self.hands_played += 1
        rec = self._record(h)
        facts = hand_facts(rec)
        hh = to_pokerstars(rec)
        self.db.insert_hand(rec, facts, hh)
        self._update_observed(h)
        day = datetime.now().strftime("%Y-%m-%d")
        path = os.path.join(self.game.data_dir, "hand_histories", "HH%s %s.txt" % (day.replace("-", ""), self.table_name.replace("$", "")))
        with open(path, "a") as f:
            f.write(hh + "\n\n\n")
        self.game.q.put(rec["id"])
        self.last_record = rec
        if self.hero.stack <= 0:
            self.busted = True

    def _record(self, h):
        seats = []
        for p in h.players:
            seats.append({"seat": p.seat, "name": p.name, "is_hero": p.is_hero,
                          "archetype": p.profile.archetype if p.profile else None,
                          "archetype_label": p.profile.label if p.profile else None,
                          "start_stack": p.start_stack, "end_stack": p.stack, "invested": p.total_bet,
                          "hole": list(p.hole), "position": h.positions[p.seat]})
        hero_live_sd = h.showdown and not self.hero.folded
        return {
            "id": h.id, "ts": now(), "session_id": self.sid, "table_name": self.table_name,
            "stakes_id": self.stakes["id"], "sb": h.sb, "bb": h.bb, "buyin": self.stakes["buyin"],
            "button_seat": h.button_seat, "hero_seat": self.hero.seat, "seats": seats,
            "actions": h.actions, "board": list(h.board), "pots": h.pots,
            "collected": {str(k): v for k, v in h.collected.items()},
            "showdown": h.showdown,
            "descriptions": {str(k): v for k, v in (h.descriptions or {}).items()},
            "hero_net": self.hero.stack - self.hero.start_stack,
            "hero_end_stack": self.hero.stack,
            "hero_cards": cards_str(self.hero.hole), "board_str": cards_str(h.board),
            "pot": sum(p["amount"] for p in h.pots), "hero_showdown": hero_live_sd,
        }

    def _update_observed(self, h):
        for p in h.players:
            o = self.observed.setdefault(p.name, {"hands": 0, "vpip": 0, "pfr": 0, "faced_bet": 0, "folded_to_bet": 0})
            o["hands"] += 1
            pre = [a for a in h.actions if a["seat"] == p.seat and a["street"] == "preflop"]
            if any(a["type"] in ("call", "raise") for a in pre):
                o["vpip"] += 1
            if any(a["type"] == "raise" for a in pre):
                o["pfr"] += 1
            for a in h.actions:
                if a["seat"] == p.seat and a["street"] != "preflop" and a["type"] in ("fold", "call", "raise") \
                        and a.get("to_call", 0) > 0:
                    o["faced_bet"] += 1
                    if a["type"] == "fold":
                        o["folded_to_bet"] += 1
