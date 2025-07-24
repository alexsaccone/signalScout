# comb through the list of markets and determine if arbitrage opportunities exist
from formulas import *
from api import *
import json
from datetime import datetime
from datetime import date
import torch

import pandas as pd
import numpy as np
from sentence_transformers import SentenceTransformer

#Some room to spare
end_of_year = datetime(2026, 1, 2).timestamp()

def filter_kalshi_events():
    # CASE 1
    # kalshi = mini_kalshi()
    # k_data = json.loads(kalshi)
    # events = k_data['markets']

    #CASE 2
    events = more_kalshi(1000)

    real_events = []

    for event in events:
        dt = event["close_time"]

        if "T" in dt:
            try:
                close_time = datetime.strptime(dt, '%Y-%m-%dT%H:%M:%S.%fZ')
            except ValueError:
                close_time = datetime.strptime(dt, '%Y-%m-%dT%H:%M:%SZ')
        else:
            close_time = datetime.strptime(dt, "%Y-%m-%d")
        liquidity = event["liquidity"]
        if close_time and close_time.timestamp() > end_of_year:
            # print("Fail condition 1 (Too long)")
            continue
        if liquidity < 2500:
            # print("Fail condition 2 (Liquidity)")
            continue
        real_events.append(event)

    print(len(events), len(real_events))
    return real_events

def filter_polymarket_events():
    events = more_poly(50)
    real_events = []

    for market in events:
        dt = market.get("endDateIso") or market.get("endDate")
        if not dt:
            continue

        if "T" in dt:
            try:
                close_time = datetime.strptime(dt, '%Y-%m-%dT%H:%M:%S.%fZ')
            except ValueError:
                close_time = datetime.strptime(dt, '%Y-%m-%dT%H:%M:%SZ')
        else:
            close_time = datetime.strptime(dt, "%Y-%m-%d")

        liquidity = float(market.get("liquidity") or market.get("liquidity_in_usd") or 0)

        if close_time.timestamp() > end_of_year:
            continue
        if liquidity < 2500:
            continue

        real_events.append(market)

    print(len(events), len(real_events))
    return real_events
     
def sentiment_analysis(kalshi, polymarket, topn=5):
    print("now starting sentiment analysis")

    model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu", trust_remote_code=False)

    kalshi = pd.DataFrame(kalshi)
    polymarket = pd.DataFrame(polymarket)
    print(f"k={len(kalshi)}, p={len(polymarket)}", flush=True)

    kalshi["bet"] = (kalshi["title"] + " " + kalshi["subtitle"] + "\n" + kalshi['rules_primary'] + "\n End date: " + kalshi["close_time"].astype(str))
    
    polymarket["bet"] = (polymarket["question"] + "\n" + polymarket["description"] + "\n End date: " + polymarket["endDateIso"].astype(str))
    
    k_emb = model.encode(kalshi["bet"].tolist(),convert_to_tensor=True,normalize_embeddings=True,batch_size=256)
    
    p_emb = model.encode(polymarket["bet"].tolist(),convert_to_tensor=True,normalize_embeddings=True,batch_size=256)

    sims = (k_emb @ p_emb.T).cpu().numpy() #Oh yeh we don't even need cosine similarity here
    k_idx, p_idx = sims.shape
    # keep only topn matches per kalshi to avoid O(k*p) dataframe explosion
    topj = np.argpartition(-sims, topn, axis=1)[:, :topn]

    rows = []
    for i in range(k_idx):
        for j in topj[i]:
            prices_raw = polymarket.iloc[j]["outcomePrices"]
            prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
            time = pd.to_datetime(kalshi.iloc[i]["close_time"], utc=True).date()
            rows.append({
                "kalshi": kalshi.iloc[i]["title"],
                "polymarket": polymarket.iloc[j]["question"],
                "similarity": sims[i, j],
                "oddsK_yes": kalshi.iloc[i]["yes_ask"],
                "oddsK_no": kalshi.iloc[i]["no_ask"],
                "oddsP_yes": float(prices[0]),
                "oddsP_no": float(prices[1]),
                "rulesK": "Primary rules: " + kalshi.iloc[i]["rules_primary"] + " Secondary rules: " + kalshi.iloc[i]["rules_secondary"],
                "rulesP": polymarket.iloc[j]["description"],
                "kalshi_close": time,
                "polymarket_close": polymarket.iloc[j]["endDateIso"]
            })

    df = pd.DataFrame(rows).sort_values("similarity", ascending=False)
    return df


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
                "rulesK": row["rulesK"],
                "rulesP": row["rulesP"]
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