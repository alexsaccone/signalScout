import pandas as pd
from google import genai
from dotenv import load_dotenv
import os
from searcher import *

def confirm_identical_criteria(df):
    prompt = "The following table is a list of different events listed on two different sites. Each row represents a diferent set of events. For each row, using the title and rules columns for Kalshi and Polymarket (appreviated to K and P respectively), determine if the resolution criteria for both events is identical. If they are identical, keep the row in, but otherwise remove the row entirely. Respond only with a csv formatted exactly like the one passed in and with no additonal text."
    table = df.to_csv(index=False)
    final_prompt = prompt + "\n\n" + table

    # client = genai.Client()
    # response = client.models.generate_content(
    #     model="gemini-2.5-flash", contents=final_prompt
    # )
    # return response.text

    return final_prompt


# load_dotenv()
events_final = confirm_identical_criteria(sentiment_analysis(filter_kalshi_events(),filter_polymarket_events()))
with open("output_final", 'w', encoding='utf-8') as f:
    f.write(events_final)