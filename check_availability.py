from engine.sportpesa import scrape_specific_matches

def check():
    # Yesterday 2025-12-15
    date_str = "15/12/25" 
    print(f"Checking matches for {date_str}...")
    matches = scrape_specific_matches(date_str)
    print(f"Found {len(matches)} matches.")
    for m in matches:
        print(m)

if __name__ == "__main__":
    check()
