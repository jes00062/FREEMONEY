import requests
import pandas as pd
from datetime import datetime
import pytz

# --------------------------- CONFIG ---------------------------
API_KEY = "f7aa230a8379043a6fee01e111290300"  # Replace with your real API key
REGION = "us"
MARKET = "h2h"
UNIT_SIZE = 1000  # bankroll
TOP_N = 10  # top N arbs per sport
ROUND_TO = 5  # round stakes to nearest 5
SPORTS = ["baseball_mlb"]  # list of sports to scan

# --------------------------- HELPERS ---------------------------
def american_to_decimal(odds):
    if odds > 0:
        return (odds / 100) + 1
    else:
        return (100 / abs(odds)) + 1

def calculate_stakes(unit, dec_home, dec_away, round_to=ROUND_TO):
    stake_home = (unit / dec_home) / ((1/dec_home) + (1/dec_away))
    stake_away = (unit / dec_away) / ((1/dec_home) + (1/dec_away))
    
    # Round to nearest multiple of round_to
    stake_home = round(stake_home / round_to) * round_to
    stake_away = round(stake_away / round_to) * round_to
    
    guaranteed_payout = max(stake_home * dec_home, stake_away * dec_away)
    profit = guaranteed_payout - (stake_home + stake_away)
    return stake_home, stake_away, profit

def format_american(odds):
    return f"+{odds}" if odds > 0 else str(odds)

def format_game_time(iso_time_str):
    utc_time = datetime.fromisoformat(iso_time_str.replace("Z", "+00:00"))
    eastern = pytz.timezone("US/Eastern")
    return utc_time.astimezone(eastern).strftime("%b %d, %Y @ %I:%M %p")

def extract_h2h_outcomes(bookmaker, home_team, away_team):
    """
    Pull only valid h2h market with both home/away teams present.
    This avoids alt lines, inning props, etc.
    """
    for market in bookmaker.get("markets", []):
        if market.get("key") == "h2h":
            names = {o["name"] for o in market["outcomes"]}
            if home_team in names and away_team in names:
                return market["outcomes"]
    return []

# --------------------------- FETCH & PARSE ODDS ---------------------------
all_rows = []

for sport in SPORTS:
    url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
    params = {
        "apiKey": API_KEY,
        "regions": REGION,
        "markets": MARKET,
        "oddsFormat": "american",
        "dateFormat": "iso"
    }
    
    response = requests.get(url, params=params)
    if response.status_code != 200:
        print(f"❌ Error fetching {sport} odds:", response.json())
        continue

    data = response.json()
    if not data:
        print(f"⚠️ No games returned for {sport}")
        continue

    for game in data:
        home_team = game["home_team"]
        away_team = game["away_team"]
        commence_time = game["commence_time"]

        for book in game["bookmakers"]:
            outcomes = extract_h2h_outcomes(book, home_team, away_team)
            if not outcomes:
                continue
            for outcome in outcomes:
                all_rows.append({
                    "sport": sport,
                    "home_team": home_team,
                    "away_team": away_team,
                    "commence_time": commence_time,
                    "bookmaker": book["title"],
                    "team": outcome["name"],
                    "odds": outcome["price"]
                })

df = pd.DataFrame(all_rows)
if df.empty:
    print("⚠️ No h2h odds data available after filtering.")
    exit()
else:
    print(f"✅ Parsed {len(df)} clean h2h outcomes into the DataFrame.")

# --------------------------- FIND ARBITRAGE ---------------------------
games = df.groupby(["sport", "home_team", "away_team", "commence_time"])
arb_list = []

for (sport, home, away, start), group in games:
    # pick best home and away odds across bookmakers
    home_candidates = group[group["team"] == home]
    away_candidates = group[group["team"] == away]
    
    if home_candidates.empty or away_candidates.empty:
        continue  # skip if missing data
    
    best_home = home_candidates.sort_values("odds", ascending=False).iloc[0]
    best_away = away_candidates.sort_values("odds", ascending=False).iloc[0]

    home_dec = american_to_decimal(best_home["odds"])
    away_dec = american_to_decimal(best_away["odds"])

    arb_percent = (1/home_dec) + (1/away_dec)

    if arb_percent < 1:
        profit_margin = (1 - arb_percent) * 100
        stake_home, stake_away, profit = calculate_stakes(UNIT_SIZE, home_dec, away_dec)

        arb_list.append({
            "sport": sport,
            "home_team": home,
            "away_team": away,
            "start_time": start,
            "home_book": best_home["bookmaker"],
            "away_book": best_away["bookmaker"],
            "home_odds": best_home["odds"],
            "away_odds": best_away["odds"],
            "profit_margin": profit_margin,
            "stake_home": stake_home,
            "stake_away": stake_away,
            "profit": profit
        })

# --------------------------- PRINT TOP N ARBS ---------------------------
if not arb_list:
    print("⚠️ No arbitrage opportunities found at this time.")
else:
    arb_df = pd.DataFrame(arb_list)
    for sport in SPORTS:
        sport_arbs = arb_df[arb_df["sport"] == sport].sort_values("profit_margin", ascending=False).head(TOP_N)
        if sport_arbs.empty:
            print(f"\n⚠️ No arbitrage opportunities found for {sport}.")
            continue

        print(f"\n🎯 Top {TOP_N} Arbitrage Opportunities for {sport.upper()}:")
        for _, arb in sport_arbs.iterrows():
            dt = datetime.fromisoformat(arb['start_time'].replace("Z", "+00:00"))
            game_date = dt.strftime("%b %d, %Y @ %I:%M %p")

            print(f"\n💰 {arb['away_team']} vs {arb['home_team']}")
            print(f"   📅 Game Date: {game_date}")
            print(f"   {arb['home_book']} → {arb['home_team']} @ {format_american(arb['home_odds'])}")
            print(f"   {arb['away_book']} → {arb['away_team']} @ {format_american(arb['away_odds'])}")
            print(f"   ✅ Profit Margin: {arb['profit_margin']:.2f}%")
            print(f"   💵 Suggested Stakes: {arb['home_team']}: ${arb['stake_home']:.2f}, {arb['away_team']}: ${arb['stake_away']:.2f}")
            print(f"   💰 Guaranteed Profit: ${arb['profit']:.2f}")
