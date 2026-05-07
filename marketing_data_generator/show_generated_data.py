from src.utils import load_json, plot_sessions_per_campaign
import pandas as pd
import sys


state = load_json('config/state.json')

n_campaigns = state.get('n_campaigns')

data = pd.read_csv(sys.argv[1], sep=';', parse_dates=["starttijd_bezoek"], date_format="%d-%m-%Y %H:%M")

sessions = data['starttijd_bezoek']
campaigns = data["campagne_ID"]

plot_sessions_per_campaign(sessions, campaigns)