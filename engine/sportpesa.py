import requests
from bs4 import BeautifulSoup
import datetime
import re

def scrape_specific_matches(target_date_str=None):
    """
    Scrapes matches from SportPesa for a specific date.
    target_date_str: "DD/MM/YY" format (e.g. "15/12/25")
    Returns a list of tuples: [(home, away, time), ...]
    """
    if not target_date_str:
        # Default to today in DD/MM/YY
        target_date_str = datetime.datetime.now().strftime("%d/%m/%y")
    
    url = "https://sportpesa.co.tz/sw/nyumbani-betting/soka-1/"
    # url = "https://sportpesa.co.tz/sw/supa-jackpot"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
    except Exception as e:
        print(f"Error fetching SportPesa: {e}")
        return []

    soup = BeautifulSoup(response.text, 'html.parser')
    matches = []

    # The structure on SportPesa often uses 'event-selection' or similar classes, 
    # but based on the research, we look for text patterns.
    # However, to be more robust, we look for the specific block structure if possible.
    # Let's try a generalized approach scanning for the date string.
    
    # We will look for elements that contain the date string
    # "15/12/25"
    
    # Find all elements that might contain the date
    # Usually these are in a 'match-time' or similar div, or just text nodes.
    # Let's iterate through all text nodes or specific containers.
    
    # Heuristic: Find the text matching the date filter
    found_elements = soup.find_all(text=re.compile(re.escape(target_date_str)))
    
    for el in found_elements:
        # el is a NavigableString. 
        # The structure is often:
        # container -> [Time Info] [Home Team] [Away Team] ...
        
        # This part is tricky without live DOM inspection of classes, 
        # so we try to find the parent match container.
        match_container = el.find_parent('div', class_=lambda x: x and 'event-row' in x if x else False) # Hypothetical
        if not match_container:
            match_container = el.find_parent('div') # excessive generic fallback
            
        if match_container:
            # Try to grab team names. 
            # Often they are in specific classes like 'team-names' or just subsequent divs.
            text_content = match_container.get_text(" | ", strip=True)
            # Expected: "15/12/25 - 23:00 | ID: 123 | Home | Away | ..."
            
            parts = text_content.split("|")
            # We need to parse this somewhat intelligently.
            
            # Since exact class names are unknown, let's look for the structure "Team A vs Team B" or just two names.
            # Let's fall back to a safer "find next strings" approach from the date element.
            pass

    # REVISED STRATEGY based on common betting site structures (and safety):
    # Betting sites usually have a list of rows. 
    # Let's look for "event-names" or similar if we can guess, 
    # BUT finding specific text is safer if we traverse siblings.
    
    seen_matches = set()

    for el in found_elements:
        try:
            # el text is like "15/12/25 - 23:00 ..."
            text_val = el.strip()
            if " - " in text_val:
                time_part = text_val.split("-")[1].strip().split("|")[0].strip() # Extract 23:00
            else:
                time_part = "00:00"

            # The next significant text nodes should be the teams.
            # Traverse siblings or parent's siblings
            # Let's look at the parent's next elements.
            
            parent = el.parent
            # Move up until we find a block that contains more info or `li` / `div` row
            row = parent
            while row and row.name not in ['li', 'tr', 'div']:
                row = row.parent
                if row and (row.get('class') and 'game-row' in str(row.get('class'))):
                   break
            
            # If we don't find a specific "row", we just look forward in the DOM from the date text.
            # Find the next 2 logical text items that look like team names (not numbers, not 'draw').
            
            current_node = el
            accumulated_text = []
            
            # Scrape next 5 text nodes
            for _ in range(10):
                current_node = current_node.find_next(text=True)
                if not current_node: break
                txt = current_node.strip()
                if txt and len(txt) > 2 and not txt.isdigit() and "ID:" not in txt and " ID " not in txt and "+" not in txt:
                     # Heuristic filters
                     accumulated_text.append(txt)
            
            if len(accumulated_text) >= 2:
                home = accumulated_text[0]
                away = accumulated_text[1]
                
                # Check duplication
                match_id = f"{home}-{away}"
                if match_id not in seen_matches:
                    matches.append((home, away))
                    seen_matches.add(match_id)
                    
        except Exception:
            continue

    return matches
