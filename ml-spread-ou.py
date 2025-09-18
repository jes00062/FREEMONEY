import requests
import pandas as pd

API_KEY = "bce96c12393280a85a6bf1fa415433af"
REGION = "us"  # us, uk, eu, au
UNIT_SIZE = 1000  # bankroll
TOP_N = 5  # top N arbs to display per sport
ROUND_TO = 5  # round stakes to nearest 5

# Only MLB and NFL
SPORTS = ["baseball_mlb", "americanfootball_nfl"]

# Valid markets per sport
SPORT_MARKETS = {
    "baseball_mlb": ["h2h", "spreads", "totals"],
    "americanfootball_nfl": ["h2h", "spreads", "totals"]
}

# ---------------------------
# Step 0: Check remaining API credits
# ---------------------------
status_url = "https://api.the-odds-api.com/v4/sports/"
status_params = {"apiKey": API_KEY}
status_response = requests.get(status_url, params=status_params)

if status_response.status_code != 200:
    print("❌ Error checking API status:", status_response.json())
else:
    remaining = status_response.headers.get("x-requests-remaining")
    if remaining:
        print(f"✅ Remaining API credits: {remaining}")
    else:
        print("⚠️ Could not detect remaining credits from API response headers.")

# ---------------------------
# Step 1: Fetch odds for all sports
# ---------------------------
all_rows = []

for sport in SPORTS:
    markets = SPORT_MARKETS.get(sport, ["h2h"])
    url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
    params = {
        "apiKey": API_KEY,
        "regions": REGION,
        "markets": ",".join(markets),
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
            book_name = book["title"]
            for market in book["markets"]:
                market_type = market["key"]  # h2h, spreads, totals
                for outcome in market["outcomes"]:
                    all_rows.append({
                        "sport": sport,
                        "home_team": home_team,
                        "away_team": away_team,
                        "commence_time": commence_time,
                        "bookmaker": book_name,
                        "market": market_type,
                        "team": outcome["name"],
                        "line": outcome.get("point", None),  # Only for spreads/totals
                        "odds": outcome["price"]
                    })

df = pd.DataFrame(all_rows)
if df.empty:
    print("⚠️ No odds data available after parsing. Check your API key or credits.")
    exit()
else:
    print(f"✅ Parsed {len(df)} odds entries into the DataFrame.")

# ---------------------------
# Step 2: Convert American odds to decimal
# ---------------------------
def american_to_decimal(odds):
    if odds > 0:
        return (odds / 100) + 1
    else:
        return (100 / abs(odds)) + 1

# ---------------------------
# Step 3: Calculate stakes (rounded)
# ---------------------------
def calculate_stakes(unit, dec_home, dec_away, round_to=ROUND_TO):
    stake_home = (unit / dec_home) / ((1/dec_home) + (1/dec_away))
    stake_away = (unit / dec_away) / ((1/dec_home) + (1/dec_away))
    
    stake_home = round(stake_home / round_to) * round_to
    stake_away = round(stake_away / round_to) * round_to
    
    guaranteed_payout = max(stake_home * dec_home, stake_away * dec_away)
    profit = guaranteed_payout - (stake_home + stake_away)
    return stake_home, stake_away, profit

# ---------------------------
# Step 4: Find arbitrage opportunities with line type
# ---------------------------
games = df.groupby(["sport", "home_team", "away_team", "commence_time"])
arb_list = []

for (sport, home, away, start), group in games:
    # Check all outcomes for home and away teams
    home_rows = group[group["team"] == home]
    away_rows = group[group["team"] == away]

    if home_rows.empty or away_rows.empty:
        continue  # skip if missing odds for either team

    # Pick best odds
    best_home = home_rows.sort_values("odds", ascending=False).iloc[0]
    best_away = away_rows.sort_values("odds", ascending=False).iloc[0]

    # Convert to decimal
    home_dec = american_to_decimal(best_home["odds"])
    away_dec = american_to_decimal(best_away["odds"])

    # Calculate arb %
    arb_percent = (1/home_dec) + (1/away_dec)

    if arb_percent < 1:
        profit_margin = (1 - arb_percent) * 100
        stake_home, stake_away, profit = calculate_stakes(UNIT_SIZE, home_dec, away_dec)

        # Detect line type from market string if available
        line_type = best_home.get("market", "ML")  # default to moneyline if missing

        arb_list.append({
            "sport": sport,
            "home_team": home,
            "away_team": away,
            "start_time": start,
            "home_book": best_home["bookmaker"],
            "away_book": best_away["bookmaker"],
            "home_odds": best_home["odds"],
            "away_odds": best_away["odds"],
            "line_type": line_type,
            "profit_margin": profit_margin,
            "stake_home": stake_home,
            "stake_away": stake_away,
            "profit": profit
        })

# ---------------------------
# Step 5: Sort and print top N arbs per sport
# ---------------------------
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
            print(f"\n💰 {arb['away_team']} vs {arb['home_team']} (Starts: {arb['start_time']})")
            print(f"   Line Type: {arb['line_type']}")
            print(f"   {arb['home_book']} → {arb['home_team']} @ {arb['home_odds']} (dec {american_to_decimal(arb['home_odds']):.2f})")
            print(f"   {arb['away_book']} → {arb['away_team']} @ {arb['away_odds']} (dec {american_to_decimal(arb['away_odds']):.2f})")
            print(f"   ✅ Profit Margin: {arb['profit_margin']:.2f}%")
            print(f"   💵 Suggested Stakes: {arb['home_team']}: ${arb['stake_home']:.2f}, {arb['away_team']}: ${arb['stake_away']:.2f}")
            print(f"   💰 Guaranteed Profit: ${arb['profit']:.2f}")
