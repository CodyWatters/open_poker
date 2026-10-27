# Vegas 6-Max

Local no-limit hold'em against bots (4 to 10 players per table), with a bankroll, four stake levels, and full hand-history analysis.

No installs needed. It only uses Python 3.9+ (already on most Macs).

## Get it

```bash
git clone https://github.com/CodyWatters/open_poker.git
cd open_poker
```

## Start

```bash
python3 server.py
```


Your browser opens at http://localhost:8765. Stop with `Ctrl+C`.
You can also double-click `play.command` in Finder.


<img width="974" height="840" alt="image" src="https://github.com/user-attachments/assets/5738cddb-d5dc-471e-a9bf-642c01bb8cb5" />

<img width="1436" height="698" alt="image" src="https://github.com/user-attachments/assets/ae97a6f7-ba89-4a97-a2d1-022de926b850" />

<img width="951" height="793" alt="image" src="https://github.com/user-attachments/assets/b218ae50-91ec-4e63-95ea-6fbaa12b3af0" />

## How it works

- You start with a **$1,000 bankroll**.
- There are four tables: **$1K, $5K, $25K, $100K** buy-ins. Blinds are 1/100 of the buy-in, so everyone starts with 100 big blinds.
- Every time you sit down, the table gets a random number of players: 4 to 10. Ranges, advice and bots adjust to the table size (for example, first to act at a 10-player table plays much tighter than at 6).
- Sitting down takes the buy-in from your bankroll. **Leave table** puts your stack back. A new table means fresh opponents who all start with the buy-in.
- A bot that busts gets replaced by a new one with a fresh stack.
- If your total chips (bankroll + table stack) fall under $200, a **Buy $1,000** button appears in the lobby. You can use it as many times as you need; the lobby counts how many.
- **Erase everything and start over** (in the lobby) deletes all hands, stats and hand-history files and resets you to $1,000.
- If you stop the server while seated, your stack from the last finished hand is cashed out the next time you start it.

## Bots

Each table draws bots from these types. Higher stakes have tougher ones:

| Type | Style |
|---|---|
| Fish | Loose and passive. Plays its own cards and ignores yours |
| Calling station | Calls too much |
| Maniac | Raises and bluffs constantly |
| Nit | Very tight |
| TAG (tight-aggressive) | Solid regular. Uses positional ranges and reads your range from your actions |
| LAG (loose-aggressive) | Wider and more aggressive regular |
| Shark | The strongest type. Low noise, more simulations, and it adapts to your stats (VPIP = how often you voluntarily put money in, and how often you fold to bets) |

How the bots decide: position-based preflop ranges, then postflop Monte Carlo equity against the ranges your actions suggest.
They're strong heuristic bots, **not** a game-theory solver. Bot types are hidden at the table and shown when you review a hand.

## Study aids (at the table, under the action log)

- **Preflop ranges**: a 13×13 chart (AA down to 22) colored raise / call / check / fold. It follows your seat and what players before you did (folded to you, limpers, a raise, a re-raise) and outlines your current hand. Untick "Follow my current hand" to explore any seat or situation.
- **Hand rankings**: cheat sheet from four of a kind down to high card, with examples and how often each hand happens.

## Analyzing your hands

Every hand is saved in `data/poker.db` (SQLite) and also appended as PokerStars-format text to `data/hand_histories/`.

In the app:
- **Hands**: filter by stakes, session, position, won/lost, showdown, big pots, cards, or flagged mistakes.
- **Analyze this hand** (at the table, right after a hand ends, or press `A`): shows everyone's cards, bot types, and the equity breakdown of each of your decisions without leaving the table.
- **Hand review**: step through the hand with every player's hole cards visible. Each of your decisions shows:
  - the pot odds you needed
  - your **equity vs. estimated ranges**: what you could have known at the table
  - your **equity vs. their actual cards**: hindsight
  - automatic flags (mistake, note, info)
- **All-in luck check**: when the money went in before the river, it shows your expected result vs. your actual result.
- **Copy for AI review**: copies the hand plus the analysis as a prompt you can paste into Claude.
- **Stats**: VPIP, PFR (preflop raise %), 3-bet, AF (aggression factor), WTSD (went to showdown), W$SD (won money at showdown), c-bet (continuation bet), and fold to c-bet. Also bb/100 (big blinds won per 100 hands), results by position and by stakes, and a results chart with an all-in-adjusted (EV, expected value) line.
- **Export for AI analysis (.zip)** (Hands or Stats page, uses current filters): one zip with instructions for the AI, a stats summary, a per-decision CSV, your costliest spots with everyone's cards, and full hand data. Give it to Claude or an agent and ask it to find your leaks.
- **Exports**: PokerStars `.txt` (imports into PokerTracker 4, Hold'em Manager 3, Hand2Note, or GTO Wizard), full JSON, and a per-decision CSV.

In PokerTracker or HM3, set your player name to `Hero`, or to whatever name you set in the lobby.

## Where the grades come from

There is no solver, no outside dataset and no third-party poker library. Every number in the hand review is computed by this repo (Python standard library only) from a few hand-written constants plus Monte Carlo simulation. Treat the grades as a solid second opinion, not ground truth.

- **Hand strength ranking** ([`pokerapp/preflop_data.py`](pokerapp/preflop_data.py)): the 169 starting hands ordered best to worst. Generated by [`tools/gen_preflop.py`](tools/gen_preflop.py): Monte Carlo equity of each hand vs. 1 and vs. 2 random hands (6,000 deals each), plus a small bonus for suited and connected hands. `hand_pct` in `ranges.py` turns your hand into "top X% of hands" using this list.
- **Preflop range sizes** ([`pokerapp/ranges.py`](pokerapp/ranges.py), `OPEN_BY_BEHIND` and `CALL_BY_BEHIND`): how wide a solid regular opens or calls, keyed by how many players are left to act. For example 6-max UTG opens the top 15%, BTN the top 45%, UTG at a 10-player table 8.5%, and the BB defends 32% vs. one raise. These are hand-tuned approximations of common strategy, not copied from a chart or solver. The same numbers drive the preflop chart at the table, the preflop grades, and the TAG / LAG / Shark bots.
- **Preflop grades** ([`pokerapp/analysis.py`](pokerapp/analysis.py), `grade_preflop` and `should_have`): compare your hand's percentile with those range sizes. Folding a top-3% hand to one raise is a *mistake*; opening a hand 1.7× wider than the range is a *loose open* note; folding a hand inside 0.8× the range is a *tight fold* note.
- **Opponent ranges** (`ranges.py`, `estimate_range`): each opponent's preflop action (open, limp, call, 3-bet…) selects a slice of the ranking (`preflop_band`). Each postflop bet / raise / call / check then scales every combo's weight by how it connects with the board (`ACCEPT_BET`, `ACCEPT_RAISE`, `ACCEPT_CALL`, `ACCEPT_CHECK`, buckets: strong / pair / draw / air). Also hand-tuned constants. Bet sizes and bot types are ignored: every opponent is modeled as the same solid regular.
- **Equity vs. ranges** (`ranges.py`, `equity_vs_ranges`): 1,200 Monte Carlo deals per decision. Each deal draws one hand per opponent from their weighted range, finishes the board, and scores with the 7-card evaluator in [`pokerapp/cards.py`](pokerapp/cards.py).
- **Equity vs. actual** (`ranges.py`, `equity_vs_hands`): the same against the cards the bots really held (the app dealt them, so it knows). Every runout is enumerated on the flop, turn and river; preflop uses 2,000 samples.
- **Equity needed** = `to call / (pot + to call)`, from the recorded action. Draws before the river get +5% for implied odds.
- **Postflop flags and the Good / Close / Improve verdict** (`analysis.py`, `analyze` and `should_have`): fixed margins against those numbers. Folding with more than 10 points of equity above the price is a *mistake*, 4–10 points is a *close fold*; calling 12+ points short is a *mistake*, 5–12 a *thin call*; bet for value from about 60% equity heads-up (+7% per extra opponent); raise from about 72% (+5% per extra opponent). The verdict compares what you did (fold / check / call / bet-or-raise) with what `should_have` recommends.
- **All-in luck check** (`analysis.py`, `allin_ev`): deals the rest of the board against the real hands (every runout when 1–2 cards are left, 2,500 samples preflop) and pays out the recorded pots to get your expected result.
- **"Typical" stat ranges** in the AI export's `summary.md` ([`pokerapp/aipack.py`](pokerapp/aipack.py), `REFS`): a hand-written table of what a solid 6-max regular runs (VPIP 22–28%, PFR 18–24%, and so on).

Known limits: the range model is simple, equity vs. ranges has a few points of sampling noise, and the thresholds are judgment calls. Differences under about 5% are noise. For a serious review, use **Copy for AI review** or the export and ask a stronger engine or a human.

## Hosting it online (optional)

```bash
python3 server.py --host 0.0.0.0 --port 8765 --no-browser
```

It's one Python process with no dependencies, so it runs on any small VPS, Fly.io, Railway, or Render. Use `PORT` and `POKER_DATA` env vars to set the port and the data folder.
There's no login, so keep it private (for example on a Tailscale network or behind basic auth).

## Files

```
server.py            web server + API
pokerapp/engine.py   rules: betting, min-raises, side pots, showdown
pokerapp/bots.py     bot types and decisions
pokerapp/ranges.py   range estimates + equity math (shared by bots and analysis)
pokerapp/analysis.py decision grading, all-in EV, stats
pokerapp/cards.py    card encoding + 7-card hand evaluator
pokerapp/preflop_data.py  169 starting hands ranked (generated)
tools/gen_preflop.py regenerates preflop_data.py by Monte Carlo
pokerapp/hh.py       PokerStars hand-history export
static/              the browser UI
data/                your database and hand-history files (created on first run)
```
