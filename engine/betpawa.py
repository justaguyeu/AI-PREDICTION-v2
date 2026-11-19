"""
BetPawa Tanzania – Match Scraper
Fetches upcoming football fixtures with league and 1X2 odds from:
  https://www.betpawa.co.tz/events/popular?categoryId=2&marketId=1X2

The page text for each event looks like:
  10:30 pm Thu 05/03
  Petrojet FC
  Talaea El Gaish
  Football / Egypt / Premier League
  1 / 2.55 / X / 2.84 / 2 / 2.98 / 85
"""
import os
import re
import time

URL ="https://www.betpawa.co.tz/events/popular?categoryId=2&marketId=1X2"
SCROLL_ROUNDS = 12

TIME_RE = re.compile(r"\d{1,2}:\d{2}\s*(?:am|pm)", re.I)
DATE_RE = re.compile(r"\d{2}/\d{2}")
ODDS_RE = re.compile(r"^\d+\.\d{1,2}$")
NUM_RE = re.compile(r"^\d+(?:\.\d+)?$")
BAD_KEYWORDS = {
    'login', 'join', 'account', 'popular', 'upcoming', 'live', 'leagues', 'markets',
    'football', 'basketball', 'sports', 'virtuals', 'pawa6', 'jackpot', 'betpawa',
    'about', 'terms', 'privacy', 'cookies', 'rules', 'help', 'responsible',
    'gambling', 'news', 'tanzania', 'change', 'licences', 'betslip', 'discover', 'learn'
}


def _is_team(s: str) -> bool:
    if NUM_RE.match(s) or TIME_RE.search(s):
        return False
    if len(s) < 2 or len(s) > 45:
        return False
    if any(re.search(rf"\b{b}\b", s.lower()) for b in BAD_KEYWORDS):
        return False
    return s[0].isupper() or s[0].isdigit()


def parse_page_text(text: str) -> list[dict]:
    """Extract events from the page's innerText."""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    events = []
    for j, line in enumerate(lines[:-2]):
        if not (TIME_RE.search(line) and DATE_RE.search(line)):
            continue
        home, away = lines[j + 1], lines[j + 2]
        if not (_is_team(home) and _is_team(away)) or home == away:
            continue
        league, odds = None, []
        for nxt in lines[j + 3: j + 14]:
            if TIME_RE.search(nxt) and DATE_RE.search(nxt):
                break                                   # next event starts
            if nxt.lower().startswith("football /"):
                league = nxt
            elif ODDS_RE.match(nxt) and len(odds) < 3:
                odds.append(float(nxt))
        events.append({
            "home": home, "away": away, "league": league,
            "odds": odds if len(odds) == 3 else None,
            "kickoff": line,
        })
    return events


def scrape_matches() -> list[dict]:
    """
    Returns a list of dicts: {home, away, league, odds: [1, X, 2] | None, kickoff}.
    """
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium_stealth import stealth
    from webdriver_manager.chrome import ChromeDriverManager

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)

    # Render Support: Use custom downloaded Chrome binary if it exists
    if os.environ.get("RENDER"):
        chrome_bin = "/opt/render/project/.render/chrome/chrome-linux64/chrome"
        if os.path.exists(chrome_bin):
            options.binary_location = chrome_bin

    driver = None
    found: dict[str, dict] = {}
    print("[BetPawa] Initializing stealth browser...")
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        stealth(driver, languages=["en-US", "en"], vendor="Google Inc.", platform="Win32",
                webgl_vendor="Intel Inc.", renderer="Intel Iris OpenGL Engine", fix_hairline=True)

        print("[BetPawa] Loading fixtures...")
        driver.get(URL)
        time.sleep(20)  # React hydration

        # The list loads more events as you scroll and may unmount old ones,
        # so parse after every scroll and merge.
        stale = 0
        for _ in range(SCROLL_ROUNDS):
            text = driver.execute_script("return document.body.innerText") or ""
            before = len(found)
            for ev in parse_page_text(text):
                key = f"{ev['home']}|{ev['away']}"
                if key not in found or (ev["odds"] and not found[key]["odds"]):
                    found[key] = ev
            stale = stale + 1 if len(found) == before else 0
            if stale >= 2:
                break
            driver.execute_script("window.scrollBy(0, document.body.scrollHeight)")
            time.sleep(3)

    except Exception as e:
        print(f"[BetPawa] Scraper error: {e}")
    finally:
        if driver:
            driver.quit()

    matches = list(found.values())
    print(f"[BetPawa] Scraper finished. Extracted {len(matches)} matches "
          f"({sum(1 for m in matches if m['odds'])} with odds).")
    return matches


def scrape_specific_matches(target_date_str=None):
    return scrape_matches()
