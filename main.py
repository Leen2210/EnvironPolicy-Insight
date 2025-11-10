from agents.data_fetcher import get_locations, get_latest_by_city, fetch_and_summarize_by_coords

# daftar lokasi di Indonesia
df_loc = get_locations(country="ID", limit=20)
print(df_loc.head())

# latest for Jakarta (agg)
df_latest = get_latest_by_city("Jakarta")
print(df_latest)

# summary by coords (contoh koordinat Monas Jakarta: lat -6.1754, lon 106.8272)
res = fetch_and_summarize_by_coords(lat=-6.1754, lon=106.8272, days=7)
print(res["summary"].tail())
