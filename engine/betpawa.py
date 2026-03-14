"""
BetPawa Tanzania – Match Scraper
Fetches today's football fixtures from:
  https://www.betpawa.co.tz/events/popular?categoryId=2&marketId=1X2
"""
import json
import time
import re

URL = "https://www.betpawa.co.tz/events/popular?categoryId=2&marketId=1X2"

def scrape_matches():
    """
    Main entry point. Returns a list of (home_team, away_team) tuples.
    Uses selenium-stealth and a robust text-pattern extraction strategy.
    """
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager
    from selenium_stealth import stealth
    import os

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    # Render Support: Use custom downloaded Chrome binary if it exists
    if os.environ.get("RENDER"):
        chrome_bin = "/opt/render/project/.render/chrome/opt/google/chrome/google-chrome"
        if os.path.exists(chrome_bin):
            options.binary_location = chrome_bin

    driver = None
    matches = []
    BAD_KEYWORDS = {
        'login', 'join', 'account', 'popular', 'upcoming', 'live', 'leagues', 'markets',
        'football', 'basketball', 'sports', 'virtuals', 'pawa6', 'jackpot', 'betpawa',
        'home', 'about', 'terms', 'privacy', 'cookies', 'rules', 'help', 'responsible',
        'gambling', 'news', 'tanzania', 'change', 'licences', 'betslip', 'discover', 'learn'
    }
    
    print("[BetPawa] Initializing stealth browser...")
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        
        stealth(driver,
                languages=["en-US", "en"],
                vendor="Google Inc.",
                platform="Win32",
                webgl_vendor="Intel Inc.",
                renderer="Intel Iris OpenGL Engine",
                fix_hairline=True)
        
        print(f"[BetPawa] Loading Popular Fixtures...")
        driver.get(URL)
        time.sleep(20) # Essential for React hydration
        
        # We capture the full page text. This is more resilient than class names.
        full_text = driver.execute_script("return document.body.innerText")
        if not full_text:
            print("[BetPawa] Could not retrieve page text.")
            return []

        # Split into lines and clean
        lines = [line.strip() for line in full_text.split('\n') if len(line.strip()) > 1]
        
        # Step 1: Delimiter-based block extraction
        # Each match on BetPawa typically starts with a time like "10:30 pm Thu 05/03"
        TIME_REGEX = r"\d{1,2}:\d{2}\s*(?:am|pm)"
        DATE_REGEX = r"\d{2}/\d{2}"
        ODDS_REGEX = r"^\d+(?:\.\d+)?$"
        
        matches = []
        seen_pairs = set()

        for j in range(len(lines) - 2):
            line = lines[j]
            # If this line looks like a match starting marker (Time + Date)
            if re.search(TIME_REGEX, line, re.I) and re.search(DATE_REGEX, line):
                # The next two lines are highly likely to be the Home and Away teams
                h = lines[j+1]
                a = lines[j+2]
                
                # Validation: 
                # - Not odds
                # - Not too long
                # - Not bad keywords
                # - Starts with Uppercase (usually)
                def is_valid_team(s):
                    if re.match(ODDS_REGEX, s): return False
                    if len(s) < 3 or len(s) > 40: return False
                    if any(b in s.lower() for b in BAD_KEYWORDS): return False
                    if not s[0].isupper() and not s[0].isdigit(): return False
                    return True

                if is_valid_team(h) and is_valid_team(a) and h != a:
                    key = f"{h.strip()}|{a.strip()}"
                    if key not in seen_pairs:
                        seen_pairs.add(key)
                        matches.append((h.strip(), a.strip()))
                        print(f"  [OK] Block Pair: {h} vs {a}")

        # Fallback: if block extraction found nothing, use the old filtered list approach
        if not matches:
            print("[BetPawa] Block extraction failed, trying filtered list fallback...")
            candidate_teams = []
            for line in lines:
                if re.search(TIME_REGEX, line, re.I): continue
                if re.match(ODDS_REGEX, line): continue
                if re.search(DATE_REGEX, line): continue
                if " / " in line: continue
                if len(line) < 3 or len(line) > 45: continue
                if any(b in line.lower() for b in BAD_KEYWORDS): continue
                candidate_teams.append(line)

            for i in range(0, len(candidate_teams) - 1, 2):
                h, a = candidate_teams[i], candidate_teams[i+1]
                if h != a:
                    matches.append((h.strip(), a.strip()))

    except Exception as e:
        print(f"[BetPawa] Scraper error: {e}")
    finally:
        if driver:
            driver.quit()

    print(f"[BetPawa] Scraper Finished. Extracted {len(matches)} unique matches.")
    for h, a in matches[:5]:
        print(f"  -> {h} vs {a}")
        
    return matches

def scrape_specific_matches(target_date_str=None):
    return scrape_matches()
