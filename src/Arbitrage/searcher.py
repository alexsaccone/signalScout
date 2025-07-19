# comb through the list of markets and determine if arbitrage opportunities exist
from formulas import arbitrage_pct, profit_pct, get_stakes, has_arbitrage, pct_return_per_day
from api import mini_kalshi, more_kalshi
import json
from datetime import datetime

import pandas as pd
import numpy as np
from sentence_transformers import SentenceTransformer

#Some room to spare
end_of_year = datetime(2026, 1, 2).timestamp()

# CASE 1
kalshi = mini_kalshi()
k_data = json.loads(kalshi)
events = k_data['markets']

#CASE 2
# events = more_kalshi()
# print(events)

real_events = []

for event in events:
    dt = event["close_time"]
    close_time = datetime.strptime(dt, "%Y-%m-%dT%H:%M:%SZ")
    liquidity = event["liquidity"]
    if close_time and close_time.timestamp() > end_of_year:
        print("Fail condition 1 (Too long)")
        continue
    if liquidity < 2500:
        print("Fail condition 2 (Liquidity)")
        continue
    real_events.append(event)

print(len(events), len(real_events))

def sentiment_analysis(kalshi, polymarket, predictit):
    model = SentenceTransformer("dunzhang/stella_en_1.5B_v5", trust_remote_code=True).cuda()
    kalshi["bet"] = kalshi["title"] + " " + kalshi["subtitle"] + "\n" + kalshi['rules_primary'] + "\n End date: " + str(kalshi["close_time"])
    polymarket["bet"] = polymarket["question"] + "\n" + polymarket["description"] + "\n End date: " + polymarket["end_date_iso"]