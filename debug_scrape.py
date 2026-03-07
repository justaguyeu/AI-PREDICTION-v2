from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium_stealth import stealth
import time
import re

URL = "https://www.betpawa.co.tz/events/popular?categoryId=2&marketId=1X2"

def debug_scrape():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    
    stealth(driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True)
    
    print(f"Loading {URL}...")
    driver.get(URL)
    time.sleep(15)
    
    print("Capturing data...")
    html = driver.page_source
    inner_text = driver.execute_script("return document.body.innerText")
    
    with open("debug_source.html", "w", encoding="utf-8") as f:
        f.write(html)
        
    with open("debug_text.txt", "w", encoding="utf-8") as f:
        f.write(inner_text)
        
    print(f"Source saved to debug_source.html ({len(html)} chars)")
    print(f"Text saved to debug_text.txt ({len(inner_text)} chars)")
    
    elements = driver.execute_script('return Array.from(document.querySelectorAll("*")).map(e => e.className).filter(c => typeof c === "string" && c.length > 0)')
    print(f"Total elements with classes: {len(elements)}")
    print("Some classes:", elements[:20])
    
    driver.quit()

if __name__ == "__main__":
    debug_scrape()
