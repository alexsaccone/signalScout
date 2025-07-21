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
p_url = "https://gamma-api.polymarket.com/markets?closed=false"

def mini_poly():
    polymarket = requests.request("GET", p_url)
    return polymarket.text

def more_poly(pages):
    cursor = None
    events = []
    with tqdm(desc="fetch-poly") as bar:
        for _ in range(pages):
            params = dict(limit=200)
            if cursor:
                params["cursor"] = cursor

            response = requests.get(p_url, params=params)
            if response.status_code != 200:
                print(f"poly error: {response.status_code}")
                break

            r = response.json()
            if isinstance(r, list):
                new_events = r
            else:
                new_events = r.get("events") or []
            if not new_events:
                print("no poly events, bailing")
                break

            events.extend(new_events)
            bar.update(len(new_events))

            if isinstance(r, dict):
                new_cursor = r.get("nextCursor")
            else:
                new_cursor = None
            if not new_cursor or new_cursor == cursor:
                print("stale poly cursor, stopping")
                break
            cursor = new_cursor

    return events

#PredictIt
pr_url = "https://www.predictit.org/api/marketdata/all/"
predict = requests.get(pr_url, headers = headers)