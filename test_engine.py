import sys
sys.path.insert(0, r'c:\Users\JOBSENHR\Desktop\FOOTBALL')

from engine.stats import get_team_stats, compute_dixon_coles_xg
from engine.poisson import all_markets

print('=== TEST 1: Bayern Munich vs Inter Milan (known teams) ===')
ts1 = get_team_stats('Bayern Munich', 'Inter Milan', use_web_fallback=False)
print(f'  Home ATK={ts1["home_attack"]}, DEF={ts1["home_defense"]}')
print(f'  Away ATK={ts1["away_attack"]}, DEF={ts1["away_defense"]}')
xg1h, xg1a = compute_dixon_coles_xg(ts1)
print(f'  xG: Bayern {xg1h:.3f} | Inter {xg1a:.3f}')
print(f'  Data source: {ts1["data_source"]}')

print()
print('=== TEST 2: Hoffenheim vs Heidenheim (weaker teams) ===')
ts2 = get_team_stats('TSG Hoffenheim', '1. FC Heidenheim', use_web_fallback=False)
xg2h, xg2a = compute_dixon_coles_xg(ts2)
print(f'  xG: Hoffenheim {xg2h:.3f} | Heidenheim {xg2a:.3f}')
print(f'  Data source: {ts2["data_source"]}')

print()
print('=== TEST 3: Poisson all_markets for Barcelona vs Real Madrid ===')
ts3 = get_team_stats('Barcelona', 'Real Madrid', use_web_fallback=False)
xg3h, xg3a = compute_dixon_coles_xg(ts3)
print(f'  xG: Barcelona {xg3h:.3f} | Real Madrid {xg3a:.3f}')
analysis = {'net_score': 0, 'form_differential': 0, 'text_volume': 0, 'injury_adjustment': 0}
markets, scores, meta = all_markets(analysis, 'Barcelona', 'Real Madrid', team_stats=ts3)
print(f'  1X2 FT: {markets["1x2_ft"]["prediction"]} @ {markets["1x2_ft"]["confidence"]}')
print(f'  BTTS: {markets["btts"]["prediction"]} @ {markets["btts"]["confidence"]}')
print(f'  O/U FT: {markets["ou_ft"]["prediction"]} @ {markets["ou_ft"]["confidence"]}')
print(f'  xG meta: {meta}')
print(f'  Top Score: {scores[0]}')

print()
print('=== VERIFY: Different teams = different xG (not flat 1.35/1.05) ===')
assert xg1h != xg2h, "xG should differ between Bayern and Hoffenheim!"
assert meta["stats_driven"] == True, "Should be stats driven!"
print(f'  Bayern xG_home {xg1h:.3f} != Hoffenheim xG_home {xg2h:.3f} -> OK')
print()
print('=== ALL TESTS PASSED ===')
