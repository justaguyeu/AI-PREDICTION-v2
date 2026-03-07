from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import time
import json

options = Options()
# Run headed to visually confirm/debug the anti-bot measures
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')
options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36')
options.add_argument('--disable-blink-features=AutomationControlled')
options.add_experimental_option('excludeSwitches', ['enable-automation'])
options.add_experimental_option('useAutomationExtension', False)

driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

print('Loading URL...')
driver.get('https://www.betpawa.co.tz/events/popular?categoryId=2&marketId=1X2')
time.sleep(12) # generous wait time

try:
    print("Checking __NEXT_DATA__ from JS Window...")
    nd = driver.execute_script("return window.__NEXT_DATA__")
    
    if nd:
        print("YES! __NEXT_DATA__ is present in window context.")
        with open('next_data.json', 'w') as f:
            json.dump(nd, f, indent=2)
            print("Saved __NEXT_DATA__ to next_data.json")
    else:
        print("NO __NEXT_DATA__ found on window object.")

    # Let's see if we see matches visually in the DOM
    elements = driver.find_elements(by="xpath", value="//*[contains(@class, 'participant') or contains(@class, 'team')]")
    print(f"Found {len(elements)} elements with participant or team in class.")
    for e in elements[:10]:
        text = e.text.strip()
        if text: print(f" - {text}")
        
    print("Capturing visible body text...")
    body_text = driver.find_element(by="tag name", value="body").text
    print(f"Body length: {len(body_text)}")
    print("Sample:\n" + body_text[:500].replace("\n", " | "))

except Exception as e:
    print(f"Error extracting data: {e}")

finally:
    driver.quit()
