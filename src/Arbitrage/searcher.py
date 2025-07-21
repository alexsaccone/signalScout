# comb through the list of markets and determine if arbitrage opportunities exist
from formulas import *
from api import *
import json
from datetime import datetime
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
    events = more_kalshi(50)

    real_events = []

    for event in events:
        dt = event["close_time"]

        if "T" in dt:
            close_time = datetime.strptime(dt, "%Y-%m-%dT%H:%M:%SZ")
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
    events = more_poly(100)
    real_events = []

    for market in events:
        dt = market.get("endDateIso") or market.get("endDate")
        if not dt:
            continue

        if "T" in dt:
            close_time = datetime.strptime(dt, "%Y-%m-%dT%H:%M:%SZ")
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

        
def sentiment_analysis(kalshi, polymarket):
    print("Now starting sentiment analysis")
    model = SentenceTransformer("all-MiniLM-L6-v2", trust_remote_code=True)

    kalshi = pd.DataFrame(kalshi)
    polymarket = pd.DataFrame(polymarket)

    kalshi["bet"] = kalshi["title"] + " " + kalshi["subtitle"] + "\n" + kalshi['rules_primary'] + "\n End date: " + kalshi["close_time"].astype(str)
    polymarket["bet"] = polymarket["question"] + "\n" + polymarket["description"] + "\n End date: " + polymarket["endDateIso"].astype(str)

    k_emb = model.encode(kalshi["bet"].tolist(), convert_to_tensor=True)
    p_emb = model.encode(polymarket["bet"].tolist(), convert_to_tensor=True)

    print("Cosine similarity")
    sims = torch.nn.functional.cosine_similarity(k_emb.unsqueeze(1), p_emb.unsqueeze(0), dim=-1).cpu().numpy()

    k_idx, p_idx = sims.shape
    print("Pandas part")

    results = []
    for i in range(k_idx):
        for j in range(p_idx):
            results.append({
                "kalshi": kalshi.iloc[i]["title"],
                "polymarket": polymarket.iloc[j]["question"],
                "similarity": sims[i][j]
            })

    df = pd.DataFrame(results).sort_values("similarity", ascending=False)
    return df

def arbitrage_analysis():
    print("doing analysis")

print(sentiment_analysis(filter_kalshi_events(), filter_polymarket_events()))
# polymarket_case()
# print(filter_kalshi_events())