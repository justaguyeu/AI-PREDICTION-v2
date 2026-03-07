import time
import re
from ddgs import DDGS
from hashlib import md5


def clean_text(text):
    text = text.lower()
    text = re.sub(r"http\S+", "", text)
    text = re.sub(r"[^a-z0-9\s\.\-]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def is_football_relevant(text):
    keywords = [
        "goal", "match", "win", "draw", "loss",
        "form", "injury", "suspended", "home",
        "away", "head to head", "h2h", "fixture"
    ]
    return any(k in text for k in keywords)


def scrape_articles(queries):
    texts = []
    seen = set()

    with DDGS() as ddgs:
        for q in queries:
            for attempt in range(3):
                try:
                    time.sleep(2 + attempt) # Increase delay with attempts
                    results = ddgs.text(q, max_results=4)
                    
                    if not results:
                        continue
                    
                    for r in results:
                         # ... process result ...
                         content = f"{r.get('title','')}. {r.get('body','')}"
                         if len(content) < 80: continue
                         content = clean_text(content)
                         if not is_football_relevant(content): continue
                         h = md5(content.encode()).hexdigest()
                         if h in seen: continue
                         seen.add(h)
                         texts.append(content)
                    
                    # If successful, break retry loop
                    break

                except Exception as e:
                    print(f"Error searching for '{q}' (Attempt {attempt+1}/3): {e}")
                    time.sleep(2)
                    continue

    return texts
