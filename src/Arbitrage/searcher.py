from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

if __package__:
    from .api import more_kalshi, more_poly
    from .formulas import arbitrage_pct, get_stakes, has_arbitrage, pct_return_per_day, profit_pct
else:
    from api import more_kalshi, more_poly
    from formulas import arbitrage_pct, get_stakes, has_arbitrage, pct_return_per_day, profit_pct


def filter_kalshi_events(now=None):
    return more_kalshi(1000, now or datetime.now(timezone.utc))


def filter_polymarket_events(now=None):
    return more_poly(50, now or datetime.now(timezone.utc))


def sentiment_analysis(kalshi, polymarket, topn=5):
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu", trust_remote_code=False)
    k_emb, p_emb = (
        model.encode(
            [f"{market['title']} {market['subtitle']}\n{market['rules']}\n{market['close_time']}" for market in markets],
            convert_to_tensor=True, normalize_embeddings=True, batch_size=256,
        )
        for markets in (kalshi, polymarket)
    )
    sims = (k_emb @ p_emb.T).cpu().numpy()
    topj = np.argpartition(-sims, topn, axis=1)[:, :topn]
    rows = []
    for i, market_k in enumerate(kalshi):
        for j in topj[i]:
            market_p = polymarket[j]
            rows.append({
                "kalshi": market_k["title"],
                "polymarket": market_p["title"],
                "similarity": sims[i, j],
                "oddsK_yes": market_k["yes_ask"] * 100,
                "oddsK_no": market_k["no_ask"] * 100,
                "oddsP_yes": market_p["yes_ask"],
                "oddsP_no": market_p["no_ask"],
                "rulesK": market_k["rules"],
                "kalshi_close": market_k["close_time"],
                "polymarket_close": market_p["close_time"],
            })
    return pd.DataFrame(rows).sort_values("similarity", ascending=False)



def arbitrage_analysis(df):
    try:
        df['kalshi_close'] = pd.to_datetime(df["kalshi_close"], utc=True, errors="coerce")
        df['polymarket_close'] = pd.to_datetime(df['polymarket_close'], utc = True, errors = "coerce")
    except Exception as e:
        print(f"Error converting date columns: {e}")
        # It's helpful to see the data that's causing the error
        print("Problematic 'kalshi_close' data:")
        print(df['kalshi_close'].head())
        return pd.DataFrame()

    today = date.today()
    filtered_df = df[df["similarity"] > 0.75].copy()
    arbitrage_events = []
    for index, row in filtered_df.iterrows():
        oddsK_yes = 100 / float(row["oddsK_yes"]) if float(row["oddsK_yes"]) != 0 else 1
        oddsP_yes = 1 / float(row["oddsP_yes"]) if float(row["oddsP_yes"]) != 0 else 1
        oddsK_no = 100 / float(row["oddsK_no"]) if float(row["oddsK_no"]) != 0 else 1
        oddsP_no = 1 / float(row["oddsP_no"]) if float(row["oddsP_no"]) != 0 else 1

        a_pct1 = arbitrage_pct(oddsK_yes, oddsP_no)
        a_pct2 = arbitrage_pct(oddsK_no, oddsP_yes)
        best_a_pct = min(a_pct1, a_pct2)
        first_better = a_pct1 < a_pct2
        if has_arbitrage(best_a_pct):
            if first_better: # if betting yes on Kalshi
                stakes = get_stakes(oddsK_yes, oddsP_no)
            else:
                stakes = get_stakes(oddsK_no, oddsP_yes)
            days = ((max(row["kalshi_close"], row["polymarket_close"])).date() - today).days
            arbitrage_events.append({
                "kalshi_name": row["kalshi"],
                "polymarket_name": row["polymarket"],
                "arbitrage_pct": best_a_pct,
                "profit_pct": profit_pct(best_a_pct),
                "kalshi_stake": stakes[0],
                "polymarket_stake": stakes[1],
                "daily_pct_return": pct_return_per_day(best_a_pct, days),
                "rulesK": row["rulesK"]
            })


    if not arbitrage_events:
        return pd.DataFrame()

    ranked_odds_df = pd.DataFrame(arbitrage_events).sort_values("daily_pct_return", ascending=False)
    return ranked_odds_df

def true_match_checker(df):
        filtered = df[df["similarity"] > 0.75]
        verified = []
        for idx, row in filtered.iterrows():
            prompt = f"Are these two markets about the same event?\nKalshi: {row['kalshi']}\nPolymarket: {row['polymarket']}\nAnswer Yes or No."
            # resp = model.generate(prompt) 
            is_same = "yes" in resp.lower()
            if is_same:
                verified.append({**row,"verified": True,"expected_profit": "placeholder"})
        return pd.DataFrame(verified)
