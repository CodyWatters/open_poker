"""SQLite storage: bankroll, sessions, hands (full JSON record + PokerStars text + analysis)."""
import json
import sqlite3
import threading
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS bankroll_log (
  id INTEGER PRIMARY KEY, ts TEXT, kind TEXT, amount INTEGER, balance INTEGER, note TEXT);
CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY, stakes_id TEXT, table_name TEXT, buyin INTEGER, sb INTEGER, bb INTEGER,
  started TEXT, ended TEXT, cashout INTEGER, last_stack INTEGER, hands INTEGER DEFAULT 0,
  status TEXT DEFAULT 'open');
CREATE TABLE IF NOT EXISTS hands (
  id INTEGER PRIMARY KEY, session_id INTEGER, ts TEXT, stakes_id TEXT, bb INTEGER,
  hero_pos TEXT, hero_cards TEXT, board TEXT, hero_net INTEGER, pot INTEGER, showdown INTEGER,
  ev_net REAL, mistakes INTEGER, notes INTEGER, analyzed INTEGER DEFAULT 0,
  record TEXT, facts TEXT, analysis TEXT, hh TEXT);
CREATE INDEX IF NOT EXISTS hands_session ON hands(session_id);
"""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DB:
    def __init__(self, path):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    def q(self, sql, args=(), one=False):
        with self.lock:
            cur = self.conn.execute(sql, args)
            rows = cur.fetchall()
        rows = [dict(r) for r in rows]
        return (rows[0] if rows else None) if one else rows

    def x(self, sql, args=()):
        with self.lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur.lastrowid

    # settings / bankroll
    def get(self, key, default=None):
        r = self.q("SELECT value FROM settings WHERE key=?", (key,), one=True)
        return json.loads(r["value"]) if r else default

    def set(self, key, value):
        self.x("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", (key, json.dumps(value)))

    def bankroll(self):
        b = self.get("bankroll")
        if b is None:
            self.set("bankroll", 1000)
            self.x("INSERT INTO bankroll_log(ts, kind, amount, balance, note) VALUES (?,?,?,?,?)",
                   (now(), "start", 1000, 1000, "Starting bankroll"))
            b = 1000
        return b

    def change_bankroll(self, delta, kind, note=""):
        with self.lock:
            b = self.bankroll() + delta
            self.set("bankroll", b)
            self.x("INSERT INTO bankroll_log(ts, kind, amount, balance, note) VALUES (?,?,?,?,?)",
                   (now(), kind, delta, b, note))
        return b

    # sessions
    def open_session(self, stakes, table_name):
        return self.x("INSERT INTO sessions(stakes_id, table_name, buyin, sb, bb, started, last_stack) "
                      "VALUES (?,?,?,?,?,?,?)",
                      (stakes["id"], table_name, stakes["buyin"], stakes["sb"], stakes["bb"], now(),
                       stakes["buyin"]))

    def close_session(self, sid, cashout):
        self.x("UPDATE sessions SET ended=?, cashout=?, last_stack=?, status='closed' WHERE id=?",
               (now(), cashout, cashout, sid))

    def open_sessions(self):
        return self.q("SELECT * FROM sessions WHERE status='open'")

    def sessions(self, limit=200):
        return self.q("SELECT s.*, (SELECT COALESCE(SUM(mistakes),0) FROM hands h WHERE h.session_id=s.id) "
                      "AS mistakes FROM sessions s ORDER BY id DESC LIMIT ?", (limit,))

    # hands
    def next_hand_id(self):
        r = self.q("SELECT COALESCE(MAX(id), 0) AS m FROM hands", one=True)
        return r["m"] + 1

    def insert_hand(self, rec, facts, hh):
        self.x("INSERT INTO hands(id, session_id, ts, stakes_id, bb, hero_pos, hero_cards, board, hero_net, pot,"
               " showdown, ev_net, record, facts, hh) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (rec["id"], rec["session_id"], rec["ts"], rec["stakes_id"], rec["bb"], facts["position"],
                rec["hero_cards"], rec["board_str"], rec["hero_net"], rec["pot"],
                1 if rec["hero_showdown"] else 0, rec["hero_net"], json.dumps(rec), json.dumps(facts), hh))
        self.x("UPDATE sessions SET hands=hands+1, last_stack=? WHERE id=?", (rec["hero_end_stack"], rec["session_id"]))

    def save_analysis(self, hid, an):
        self.x("UPDATE hands SET analysis=?, analyzed=1, mistakes=?, notes=?, ev_net=? WHERE id=?",
               (json.dumps(an), an["mistakes"], an["notes"], an["ev_net"], hid))

    def unanalyzed(self):
        return [r["id"] for r in self.q("SELECT id FROM hands WHERE analyzed=0 ORDER BY id")]

    def hand(self, hid):
        r = self.q("SELECT * FROM hands WHERE id=?", (hid,), one=True)
        if not r:
            return None
        r["record"] = json.loads(r["record"])
        r["facts"] = json.loads(r["facts"]) if r["facts"] else {}
        r["analysis"] = json.loads(r["analysis"]) if r["analysis"] else None
        return r

    def hand_rows(self, where="1=1", args=(), cols="*", order="id"):
        return self.q("SELECT %s FROM hands WHERE %s ORDER BY %s" % (cols, where, order), args)
