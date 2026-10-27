# Vegas 6-Max

Local 6-max no-limit hold'em against bots, with a bankroll, four stake levels, and full hand-history analysis.

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

## How it works

- You start with a **$1,000 bankroll**.
- There are four tables: **$1K, $5K, $25K, $100K** buy-ins. Blinds are 1/100 of the buy-in, so everyone starts with 100 big blinds.
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
pokerapp/hh.py       PokerStars hand-history export
static/              the browser UI
data/                your database and hand-history files (created on first run)
```
