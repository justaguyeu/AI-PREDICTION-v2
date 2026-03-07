import undetected_chromedriver as uc
from bs4 import BeautifulSoup
import time
import re

def test_uc():
    options = uc.ChromeOptions()
    options.add_argument('--headless')
    
    print("Starting UC Browser...")
    driver = uc.Chrome(options=options)
    
    print("Loading BetPawa...")
    driver.get("https://www.betpawa.co.tz/events/popular?categoryId=2&marketId=1X2")
    
    # Wait for hydration
    time.sleep(15)
    
    html = driver.page_source
    print("Loaded HTML length:", len(html))
    
    soup = BeautifulSoup(html, 'html.parser')
    all_text = ' '.join(soup.stripped_strings)
    
    # Simple regex to catch Home vs Away
    pairs = re.findall(
        r"([A-Z][A-Za-z0-9\s\.&'\-]+?)\s+(?:vs?\.?|–)\s+([A-Z][A-Za-z0-9\s\.&'\-]+)", 
        all_text
    )
    
    BAD = {'Popular', 'Football', 'Basketball', 'Markets', 'Login', 'Sign', 'Home', 'Away', 'Score', 'Odds', 'Bet'}
    matches = []
    
    for h, a in pairs:
        h, a = h.strip(), a.strip()
        if len(h) > 2 and len(a) > 2 and not any(b in h or b in a for b in BAD):
            matches.append((h, a))
            
    print(f"Found {len(matches)} matches: ")
    for m in set(matches):
        print(" -", m)
        
    driver.quit()

if __name__ == '__main__':
    test_uc()
