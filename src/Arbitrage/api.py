# access various APIs and compound similar markets in some sort of list

import requests
from tqdm import tqdm
import json

headers = {"accept": "application/json"}

#Kalshi
k_url = "https://api.elections.kalshi.com/trade-api/v2/markets"

def mini_kalshi():
    kalshi = requests.get(k_url, headers=headers)
    return kalshi.text

def more_kalshi(pages):
    cursor = None
    events = []
    with tqdm(desc="fetch") as bar:
        for _ in range(pages):
            params = dict(limit=200, with_nested_markets=True)
            if cursor:
                params["cursor"] = cursor

            response = requests.get(k_url, params=params)
            if response.status_code != 200:
                print(f"error: {response.status_code}")
                break

            r = response.json()
            new_events = r.get("markets") or []
            if not new_events:
                print("no events found, bailing")
                break

            events.extend(new_events)
            bar.update(len(new_events))

            new_cursor = r.get("cursor")
            if not new_cursor or new_cursor == cursor:
                print("stale cursor, stopping")
                break
            cursor = new_cursor

    return events



#Polymarket
p_url = "https://gamma-api.polymarket.com/markets"

def mini_poly():
    polymarket = requests.request("GET", p_url)
    return polymarket.text

def more_poly(pages):
    limit = 500
    offset = 0
    all_markets = []

    for i in range(pages):
        url = f"{p_url}?limit={limit}&offset={offset}&closed=false"
        response = requests.get(url)
        
        if response.status_code != 200:
            print(f"Error: Received status code {response.status_code}")
            break

        markets = response.json()
        all_markets.extend(markets)

        # Stop if fewer markets than limit are returned or response is empty
        if len(markets) < limit or not markets:
            break

        offset += limit

    return all_markets

#PredictIt
pr_url = "https://www.predictit.org/api/marketdata/all/"
predict = requests.get(pr_url, headers = headers)

