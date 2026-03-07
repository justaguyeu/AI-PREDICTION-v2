from duckduckgo_search import DDGS

def test_search():
    print("Testing DDGS...")
    try:
        with DDGS() as ddgs:
            results = ddgs.text("Manchester United vs Bournemouth prediction", max_results=5)
            print(f"Results type: {type(results)}")
            results_list = list(results)
            print(f"Results found: {len(results_list)}")
            for r in results_list:
                print(r)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_search()
