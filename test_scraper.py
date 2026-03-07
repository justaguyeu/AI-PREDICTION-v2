from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from bs4 import BeautifulSoup
from webdriver_manager.chrome import ChromeDriverManager
import time
import json

options = Options()
# Running headed to see what's happening
# options.add_argument('--headless=new') 
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')
options.add_argument('--disable-blink-features=AutomationControlled')
options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36')
options.add_experimental_option("excludeSwitches", ["enable-automation"])
options.add_experimental_option("useAutomationExtension", False)

try:
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    url = 'https://www.betpawa.co.tz/events/popular?categoryId=2&marketId=1X2'
    print(f"Loading {url} ...")
    driver.get(url)
    
    # Wait for potential Cloudflare/bot checks
    time.sleep(8)
    
    html = driver.page_source
    print(f"Page loaded. HTML length: {len(html)}")
    
    soup = BeautifulSoup(html, 'html.parser')
    
    nd = soup.find('script', id='__NEXT_DATA__')
    if nd:
        print(f"Found __NEXT_DATA__ (length: {len(nd.string)})")
        try:
            data = json.loads(nd.string)
            print("Successfully parsed Next.js JSON.")
            
            # Check what's inside
            matches = []
            seen = set()
            def _walk(obj):
                if isinstance(obj, dict):
                    home = obj.get('homeTeam')
                    away = obj.get('awayTeam')
                    if not home: home = obj.get('home')
                    if not away: away = obj.get('away')
                    if not home: home = obj.get('homeName')
                    if not away: away = obj.get('awayName')
                    
                    if home and away and isinstance(home, str) and isinstance(away, str):
                        key = home + '|' + away
                        if key not in seen:
                            seen.add(key)
                            matches.append((home, away))
                    for v in obj.values(): _walk(v)
                elif isinstance(obj, list):
                    for item in obj: _walk(item)
            _walk(data)
            print(f"Walked JSON. Found {len(matches)} matches.")
            if matches:
                for m in matches[:5]: print(f" - {m[0]} vs {m[1]}")
                
        except Exception as e:
            print(f"Error parsing JSON: {e}")
    else:
        print("NO __NEXT_DATA__ FOUND.")
    
    # Check DOM fallback
    rows = soup.find_all(True, class_=lambda c: c and ('event' in c or 'match' in c))
    print(f"Found {len(rows)} DOM elements with 'event' or 'match' in class.")
    
finally:
    try:
        driver.quit()
    except:
        pass
