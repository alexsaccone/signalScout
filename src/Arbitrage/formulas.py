# Takes in the decimal odds of two bets and returns the percentage of an arbitrage opportunity
def arbitrage_pct(odds1: float, odds2: float):
    return (1.0 / odds1) + (1.0 / odds2)

# Takes in an arbitrage percetnage and returns the guaranteed profit returns as a percetage
def profit_pct(p: float):
    return 1.0 - p

# Takes in the decimal odds of two bets and returns a tuple of the percentages of the total investment that should be placed in each
def get_stakes(odds1: float, odds2: float):
    arb_pct = arbitrage_pct(odds1, odds2)
    stake1 = 1.0 / (arb_pct * odds1)
    stake2 = 1.0 / (arb_pct * odds2)
    return (stake1, stake2)

# Takes in an arbitrage percentage and returns true if there is an arbitrage opportunity, false otherwise
def has_arbitrage(p: float):
    return (p < 1.0)

# Takes in an arbitrage percentage and returns the percentage return per day
def pct_return_per_day(p: float, days: int):
    return ((1.0 + profit_pct(p)) ** (1.0 / days)) - 1.0