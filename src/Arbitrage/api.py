# access various APIs and compound similar markets in some sort of list

import requests
from tqdm import tqdm

headers = {"accept": "application/json"}

#Kalshi
k_url = "https://api.elections.kalshi.com/trade-api/v2/events"
kalshi = requests.get(k_url, headers=headers)

def more_kalshi():
    cursor = ""
    events = []
    total_markets = float('inf')
    with tqdm(total=total_markets, desc = "fetch") as progress_bar:
        while True:
            response = requests.get(k_url, params = dict(limit = 200, cursor = cursor, with_nested_markets = True))
            r = response.json()
            if r.get("cursor") == cursor or not r.get("cursor"):
                break
            events.extend(r.get("events"))
            cursor = r.get("cursor")
            progress_bar.update(len(events))


#Polymarket
p_url = "https://gamma-api.polymarket.com/events"
polymarket = requests.request("GET", p_url)

#PredictIt
pr_url = "https://www.predictit.org/api/marketdata/all/"
predict = requests.get(pr_url, headers = headers)