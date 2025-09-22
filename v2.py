import requests
import pandas as pd

API_KEY = "bce96c12393280a85a6bf1fa415433af"  # replace with your Odds API key
SPORT = "baseball_mlb"   # just one sport for now
REGION = "us"
MARKETS = "h2h"
UNIT_SIZE = 1000

# ---------------------------
# Step 1: Fetch odds
# ---------------------------
url = f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds/"
params = {
    "apiKey": API_KEY,
    "regions": REGION,
    "markets": MARKETS,
    "oddsFormat": "american",
    "dateFormat": "iso"
}

response = requests.get(url, params=params)
if response.status_code != 200:
    print("❌ Error fetching odds:", response.json())
    exit()

games = response.json()
rows = []

for game in games:
    for book in game["bookmakers"]:
        for market in book["markets"]:
            for outcome in market["outcomes"]:
                rows.append({
                    "home_team": game["home_team"],
                    "away_team": game["away_team"],
                    "commence_time": game["commence_time"],
                    "bookmaker": book["title"],
                    "team": outcome["name"],
                    "odds": outcome["price"]
                })

df = pd.DataFrame(rows)
print(f"✅ Parsed {len(df)} rows")

# ---------------------------
# Step 2: Helper funcs
# ---------------------------
def american_to_decimal(odds):
    if odds > 0:
        return (odds / 100) + 1
    else:
        return (100 / abs(odds)) + 1

# ---------------------------
# Step 3: Arb Calculation
# ---------------------------
arb_list = []

games = df.groupby(["home_team", "away_team", "commence_time"])
for (home, away, start), group in games:
    home_rows = group[group["team"] == home]
    away_rows = group[group["team"] == away]

    if home_rows.empty or away_rows.empty:
        continue

    best_home = home_rows.sort_values("odds", ascending=False).iloc[0]
    best_away = away_rows.sort_values("odds", ascending=False).iloc[0]

    dec_home = american_to_decimal(best_home["odds"])
    dec_away = american_to_decimal(best_away["odds"])

    arb_percent = (1/dec_home) + (1/dec_away)

    if arb_percent < 1:
        profit_margin = (1 - arb_percent) * 100
        arb_list.append({
            "home": home,
            "away": away,
            "home_book": best_home["bookmaker"],
            "away_book": best_away["bookmaker"],
            "home_odds": best_home["odds"],
            "away_odds": best_away["odds"],
            "profit_margin": profit_margin
        })

# ---------------------------
# Step 4: Print Results
# ---------------------------
if not arb_list:
    print("⚠️ No arbitrage opportunities found")
else:
    for arb in arb_list:
        print(f"\n💰 {arb['away']} vs {arb['home']} (ML)")
        print(f"   {arb['home_book']} → {arb['home']} @ {arb['home_odds']}")
        print(f"   {arb['away_book']} → {arb['away']} @ {arb['away_odds']}")
        print(f"   ✅ Profit Margin: {arb['profit_margin']:.2f}%")
