"""Cards, 7-card hand evaluator, and hand descriptions.

Card encoding: int 0..51, rank = c >> 2 (0 = deuce .. 12 = ace), suit = c & 3.
Hand score: comparable int, (category << 20) | up to five 4-bit ranks.
"""

RANKS = "23456789TJQKA"
SUITS = "cdhs"
RANK_NAME = ["Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
             "Ten", "Jack", "Queen", "King", "Ace"]
RANK_PLURAL = ["Twos", "Threes", "Fours", "Fives", "Sixes", "Sevens", "Eights",
               "Nines", "Tens", "Jacks", "Queens", "Kings", "Aces"]
CATEGORY = ["High card", "Pair", "Two pair", "Three of a kind", "Straight",
            "Flush", "Full house", "Four of a kind", "Straight flush"]

# (high rank, bitmask) from highest straight down to the wheel (A-2-3-4-5).
STRAIGHTS = [(h, sum(1 << (h - i) for i in range(5))) for h in range(12, 3, -1)]
STRAIGHTS.append((3, (1 << 12) | 0b1111))

FULL_DECK = list(range(52))


def card_str(c):
    return RANKS[c >> 2] + SUITS[c & 3]


def cards_str(cs):
    return " ".join(card_str(c) for c in cs)


def parse_card(s):
    return RANKS.index(s[0].upper()) * 4 + SUITS.index(s[1].lower())


def _straight_high(mask):
    for h, m in STRAIGHTS:
        if mask & m == m:
            return h
    return -1


def _top(mask, n):
    out = []
    r = 12
    while r >= 0 and len(out) < n:
        if mask & (1 << r):
            out.append(r)
        r -= 1
    return out


def _pack(cat, ranks):
    v = cat
    for i in range(5):
        v = (v << 4) | (ranks[i] if i < len(ranks) else 0)
    return v


def evaluate(cards):
    """Score the best 5-card hand from 5-7 cards. Higher is better."""
    rc = [0] * 13
    sc = [0, 0, 0, 0]
    sm = [0, 0, 0, 0]
    mask = 0
    for c in cards:
        r = c >> 2
        s = c & 3
        rc[r] += 1
        sc[s] += 1
        sm[s] |= 1 << r
        mask |= 1 << r

    flush_mask = 0
    for s in range(4):
        if sc[s] >= 5:
            flush_mask = sm[s]
            h = _straight_high(flush_mask)
            if h >= 0:
                return _pack(8, [h])
            break

    quads = trips = -1
    trips2 = -1
    pairs = []
    for r in range(12, -1, -1):
        n = rc[r]
        if n == 4:
            quads = r
        elif n == 3:
            if trips < 0:
                trips = r
            elif trips2 < 0:
                trips2 = r
        elif n == 2:
            pairs.append(r)

    if quads >= 0:
        k = _top(mask & ~(1 << quads), 1)
        return _pack(7, [quads] + k)
    if trips >= 0 and (trips2 >= 0 or pairs):
        p = max(trips2, pairs[0] if pairs else -1)
        return _pack(6, [trips, p])
    if flush_mask:
        return _pack(5, _top(flush_mask, 5))
    h = _straight_high(mask)
    if h >= 0:
        return _pack(4, [h])
    if trips >= 0:
        return _pack(3, [trips] + _top(mask & ~(1 << trips), 2))
    if len(pairs) >= 2:
        p1, p2 = pairs[0], pairs[1]
        k = _top(mask & ~(1 << p1) & ~(1 << p2), 1)
        return _pack(2, [p1, p2] + k)
    if pairs:
        p = pairs[0]
        return _pack(1, [p] + _top(mask & ~(1 << p), 3))
    return _pack(0, _top(mask, 5))


def category(score):
    return score >> 20


def _ranks_of(score):
    return [(score >> (16 - 4 * i)) & 15 for i in range(5)]


def describe(score):
    """PokerStars-style hand description, e.g. 'a pair of Kings'."""
    cat = category(score)
    r = _ranks_of(score)
    if cat == 8:
        if r[0] == 12:
            return "a Royal Flush"
        low = "Ace" if r[0] == 3 else RANK_NAME[r[0] - 4]
        return "a straight flush, %s to %s" % (low, RANK_NAME[r[0]])
    if cat == 7:
        return "four of a kind, %s" % RANK_PLURAL[r[0]]
    if cat == 6:
        return "a full house, %s full of %s" % (RANK_PLURAL[r[0]], RANK_PLURAL[r[1]])
    if cat == 5:
        return "a flush, %s high" % RANK_NAME[r[0]]
    if cat == 4:
        low = "Ace" if r[0] == 3 else RANK_NAME[r[0] - 4]
        return "a straight, %s to %s" % (low, RANK_NAME[r[0]])
    if cat == 3:
        return "three of a kind, %s" % RANK_PLURAL[r[0]]
    if cat == 2:
        return "two pair, %s and %s" % (RANK_PLURAL[r[0]], RANK_PLURAL[r[1]])
    if cat == 1:
        return "a pair of %s" % RANK_PLURAL[r[0]]
    return "high card %s" % RANK_NAME[r[0]]


def hand_class(hole):
    """'AKs', 'AKo', or 'TT' for a two-card hand."""
    a, b = sorted(hole, key=lambda c: c >> 2, reverse=True)
    ra, rb = a >> 2, b >> 2
    if ra == rb:
        return RANKS[ra] * 2
    return RANKS[ra] + RANKS[rb] + ("s" if (a & 3) == (b & 3) else "o")


ALL_COMBOS = [(a, b) for a in range(52) for b in range(a)]  # 1326 combos
