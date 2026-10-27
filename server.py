#!/usr/bin/env python3
"""Vegas 6-Max: local poker app. Run:  python3 server.py   then open http://localhost:8765"""
import argparse
import csv
import io
import json
import mimetypes
import os
import sys
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from pokerapp.analysis import aggregate, analyze, ANALYSIS_VERSION  # noqa: E402
from pokerapp.cards import card_str  # noqa: E402
from pokerapp.game import Game, STAKES  # noqa: E402
from pokerapp.hh import hand_number  # noqa: E402
from pokerapp.aipack import build_pack  # noqa: E402
from datetime import datetime  # noqa: E402

GAME = None
STATIC = os.path.join(ROOT, "static")


def hand_filters(qs):
    where, args = ["1=1"], []
    g = lambda k: (qs.get(k) or [""])[0]
    if g("stakes"):
        where.append("stakes_id=?"); args.append(g("stakes"))
    if g("session"):
        where.append("session_id=?"); args.append(int(g("session")))
    if g("pos"):
        where.append("hero_pos=?"); args.append(g("pos"))
    if g("result") == "won":
        where.append("hero_net>0")
    elif g("result") == "lost":
        where.append("hero_net<0")
    if g("showdown") == "1":
        where.append("showdown=1")
    if g("flagged") == "1":
        where.append("mistakes>0")
    elif g("flagged") == "notes":
        where.append("(mistakes>0 OR notes>0)")
    if g("bigpot") == "1":
        where.append("pot >= bb*40")
    if g("cards"):
        where.append("hero_cards LIKE ?"); args.append("%" + g("cards") + "%")
    return " AND ".join(where), args


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json", headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def do_GET(self):
        try:
            self._get()
        except Exception as e:
            traceback.print_exc()
            self._send(500, {"error": str(e)})

    def do_POST(self):
        try:
            self._post()
        except ValueError as e:
            self._send(400, {"error": str(e)})
        except Exception as e:
            traceback.print_exc()
            self._send(500, {"error": str(e)})

    # ---------------------------------------------------------------- GET
    def _get(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        path = u.path
        db = GAME.db
        if path == "/api/lobby":
            return self._send(200, GAME.lobby())
        if path == "/api/state":
            return self._send(200, GAME.state())
        if path == "/api/live_ev":
            return self._send(200, GAME.live_ev())
        if path == "/api/preflop_ranges":
            g = lambda k: (qs.get(k) or [None])[0] or None
            return self._send(200, GAME.preflop_ranges(g("pos"), g("sit")))
        if path == "/api/sessions":
            return self._send(200, db.sessions(500))
        if path == "/api/hands":
            where, args = hand_filters(qs)
            rows = db.hand_rows(where, args, cols="id, session_id, ts, stakes_id, bb, hero_pos, hero_cards, board, "
                                "hero_net, pot, showdown, ev_net, mistakes, notes, analyzed", order="id DESC")
            return self._send(200, rows[:3000])
        if path.startswith("/api/hand/"):
            hid = int(path.rsplit("/", 1)[1])
            r = GAME.db.hand(hid)
            if not r:
                return self._send(404, {"error": "not found"})
            if not r["analysis"] or r["analysis"].get("v", 1) < ANALYSIS_VERSION:
                r["analysis"] = analyze(r["record"])
                db.save_analysis(hid, r["analysis"])
            rec = r["record"]
            for s in rec["seats"]:
                s["hole_str"] = [card_str(c) for c in s["hole"]]
            rec["board_cards"] = [card_str(c) for c in rec["board"]]
            r["hand_number"] = hand_number(rec)
            ids = [x["id"] for x in db.hand_rows("1=1", (), cols="id")]
            k = ids.index(hid)
            r["prev_id"] = ids[k - 1] if k > 0 else None
            r["next_id"] = ids[k + 1] if k + 1 < len(ids) else None
            return self._send(200, r)
        if path == "/api/stats":
            where, args = hand_filters(qs)
            rows = db.hand_rows(where, args, cols="id, ts, stakes_id, bb, hero_net, ev_net, mistakes, facts, showdown")
            rows2 = [{"id": r["id"], "facts": json.loads(r["facts"]), "bb": r["bb"], "net": r["hero_net"],
                      "ev_net": r["ev_net"], "stakes_id": r["stakes_id"], "mistakes": r["mistakes"],
                      "showdown_hero": r["showdown"], "ts": r["ts"]} for r in rows]
            out = aggregate(rows2)
            out["pending_analysis"] = GAME.q.qsize()
            return self._send(200, out)
        if path.startswith("/api/export/"):
            return self._export(path.rsplit("/", 1)[1], qs)
        # static
        if path == "/":
            path = "/index.html"
        fp = os.path.normpath(os.path.join(STATIC, path.lstrip("/")))
        if not fp.startswith(STATIC) or not os.path.isfile(fp):
            return self._send(404, "not found", "text/plain")
        with open(fp, "rb") as f:
            data = f.read()
        self._send(200, data, mimetypes.guess_type(fp)[0] or "application/octet-stream")

    def _export(self, what, qs):
        where, args = hand_filters(qs)
        db = GAME.db
        if what == "ai_pack.zip":
            body = build_pack(db, where, args, GAME.hero_name)
            name = "poker_analysis_%s.zip" % datetime.now().strftime("%Y%m%d_%H%M")
            return self._send(200, body, "application/zip",
                              {"Content-Disposition": 'attachment; filename="%s"' % name})
        if what == "hands.txt":
            rows = db.hand_rows(where, args, cols="hh")
            body = "\n\n\n".join(r["hh"].rstrip() for r in rows) + "\n"
            return self._send(200, body, "text/plain; charset=utf-8",
                              {"Content-Disposition": 'attachment; filename="vegas6max_hands_pokerstars.txt"'})
        if what == "hands.json":
            rows = db.hand_rows(where, args, cols="id, record, analysis, facts")
            out = [{"id": r["id"], "record": json.loads(r["record"]),
                    "analysis": json.loads(r["analysis"]) if r["analysis"] else None,
                    "facts": json.loads(r["facts"])} for r in rows]
            return self._send(200, json.dumps(out, indent=1), "application/json",
                              {"Content-Disposition": 'attachment; filename="vegas6max_hands.json"'})
        if what == "decisions.csv":
            rows = db.hand_rows(where, args, cols="id, stakes_id, hero_pos, hero_cards, hero_net, analysis")
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["hand_id", "stakes", "position", "hole", "street", "board", "action", "amount", "pot",
                        "to_call", "equity_needed", "equity_vs_ranges", "equity_vs_actual", "opponents", "flags",
                        "hand_net"])
            for r in rows:
                if not r["analysis"]:
                    continue
                for d in json.loads(r["analysis"])["decisions"]:
                    w.writerow([r["id"], r["stakes_id"], r["hero_pos"], r["hero_cards"], d["street"], d["board"],
                                d["action"], d["amount"], d["pot"], d["to_call"], d["req"], d["eq_range"],
                                d["eq_actual"], d["opponents"],
                                " | ".join("%s: %s" % (f["level"], f["text"]) for f in d["flags"]), r["hero_net"]])
            return self._send(200, buf.getvalue(), "text/csv",
                              {"Content-Disposition": 'attachment; filename="vegas6max_decisions.csv"'})
        return self._send(404, {"error": "unknown export"})

    # ---------------------------------------------------------------- POST
    def _post(self):
        path = urlparse(self.path).path
        b = self._body()
        if path == "/api/join":
            return self._send(200, {"frames": GAME.join(b["stakes"])})
        if path == "/api/act":
            amt = b.get("amount")
            return self._send(200, {"frames": GAME.act(b["action"], int(amt) if amt is not None else None)})
        if path == "/api/next":
            return self._send(200, {"frames": GAME.next_hand()})
        if path == "/api/leave":
            return self._send(200, GAME.leave())
        if path == "/api/topup":
            return self._send(200, GAME.top_up())
        if path == "/api/erase_all":
            return self._send(200, GAME.erase_all())
        if path == "/api/hero_name":
            return self._send(200, GAME.set_hero_name(b.get("name", "Hero")))
        return self._send(404, {"error": "unknown endpoint"})


def main():
    global GAME
    ap = argparse.ArgumentParser(description="Vegas 6-Max poker")
    ap.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to allow other devices/hosting")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8765)))
    ap.add_argument("--data", default=os.environ.get("POKER_DATA", os.path.join(ROOT, "data")))
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    GAME = Game(a.data)
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    url = "http://localhost:%d" % a.port
    print("Vegas 6-Max running at %s  (data: %s)  Ctrl+C to stop." % (url, a.data))
    if not a.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped. If you were seated, your stack is cashed out next time you start.")


if __name__ == "__main__":
    main()
