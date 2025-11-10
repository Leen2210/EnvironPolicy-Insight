# data_fetcher.py
import os
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
import requests
import pandas as pd
from dotenv import load_dotenv
from math import radians, cos, sin, asin, sqrt
from geopy.geocoders import Nominatim

load_dotenv()

OPENAQ_API_BASE = "https://api.openaq.org/v3"
OPENAQ_API_KEY = os.getenv("OPENAQ_API_KEY", "none")
headers = {"X-API-Key": OPENAQ_API_KEY} if OPENAQ_API_KEY else {}


# Cache config
CACHE_DIR = Path(os.getenv("CACHE_DIR", "data/cache"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_TTL_HOURS = int(os.getenv("CACHE_TTL_HOURS", "6"))


def _cache_write(name: str, data):
    path = CACHE_DIR / f"{name}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"ts": time.time(), "data": data}, f)


def _cache_read(name: str):
    path = CACHE_DIR / f"{name}.json"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        obj = json.load(f)
    ts = obj.get("ts", 0)
    if time.time() - ts > CACHE_TTL_HOURS * 3600:
        return None
    return obj.get("data")


def _request_json(url, params=None, use_cache=False, cache_name=None):
    if use_cache and cache_name:
        cached = _cache_read(cache_name)
        if cached is not None:
            return cached

    headers = {}
    if OPENAQ_API_KEY and OPENAQ_API_KEY.lower() != "none":
        headers["x-api-key"] = OPENAQ_API_KEY

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if use_cache and cache_name:
            _cache_write(cache_name, data)
        return data
    except Exception as e:
        print(f"[data_fetcher] Request error: {e} - URL: {url} - params: {params}")
        return None


# ----------------------------
# Utility: haversine distance
# ----------------------------
def haversine(lon1, lat1, lon2, lat2):
    # all args in decimal degrees
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    km = 6371 * c
    return km


# ----------------------------
# Get list of locations (stations)
# ----------------------------

def get_locations(country_code="ID", limit=200):
    """Ambil daftar lokasi pemantauan udara dari OpenAQ v3 dan filter berdasarkan country code"""
    try:
        params = {"limit": limit}
        res = requests.get(f"{OPENAQ_API_BASE}/locations", params=params, headers=headers, timeout=15)
        res.raise_for_status()
        data = res.json().get("results", [])

        if not data:
            print("[data_fetcher] Tidak ada data ditemukan.")
            return None

        # Filter lokasi hanya yang berada di negara tertentu
        data_filtered = [
            loc for loc in data if loc.get("country", {}).get("code") == country_code
        ]

        if not data_filtered:
            print(f"[data_fetcher] Tidak ada data untuk negara {country_code}")
            return None

        df = pd.DataFrame(data_filtered)
        # Ekstrak koordinat dan info penting
        df["latitude"] = df["coordinates"].apply(lambda c: c.get("latitude") if c else None)
        df["longitude"] = df["coordinates"].apply(lambda c: c.get("longitude") if c else None)
        df["country_name"] = df["country"].apply(lambda c: c.get("name") if c else None)
        df["country_code"] = df["country"].apply(lambda c: c.get("code") if c else None)

        cols = ["id", "name", "locality", "country_name", "latitude", "longitude", "lastUpdated"]
        existing = [c for c in cols if c in df.columns]
        return df[existing]

    except requests.RequestException as e:
        print(f"[data_fetcher] Request error: {e}")
        return None


def get_air_quality_by_coords(lat, lon, radius_km=200):
    """
    Ambil data kualitas udara berdasarkan latitude dan longitude.
    Jika lokasi utama tidak memiliki data, otomatis mencari stasiun terdekat.

    Sumber data: Open-Meteo Air Quality API
    """
    base_url = "https://air-quality-api.open-meteo.com/v1/air-quality"

    def fetch_data(latitude, longitude):
        """Helper function untuk request data dari koordinat tertentu"""
        url = (
            f"{base_url}?latitude={latitude}&longitude={longitude}"
            "&hourly=pm10,pm2_5,carbon_monoxide,nitrogen_dioxide,sulphur_dioxide,ozone"
            "&timezone=auto"
        )
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        if "hourly" not in data:
            return None

        df = pd.DataFrame(data["hourly"])
        df["time"] = pd.to_datetime(df["time"])
        return df

    # 🟩 1️⃣ Coba ambil data langsung dari lokasi user
    try:
        df = fetch_data(lat, lon)
        if df is not None:
            # Dapatkan nama lokasi via reverse geocoding
            geolocator = Nominatim(user_agent="environpolicy_insight")
            try:
                location = geolocator.reverse((lat, lon), language="id")
                city_name = location.raw["address"].get("city") or \
                            location.raw["address"].get("town") or \
                            location.raw["address"].get("state") or "Tidak diketahui"
            except Exception:
                city_name = "Tidak diketahui"

            print(f"[data_fetcher] Found direct data for {city_name} ({lat:.4f}, {lon:.4f})")

            return {
                "data": df,
                "location_name": city_name,
                "latitude": lat,
                "longitude": lon,
                "source": "Open-Meteo Air Quality API"
            }

        else:
            print(f"[data_fetcher] No data found for ({lat:.4f}, {lon:.4f}). Trying nearest station...")

    except requests.exceptions.RequestException as e:
        print(f"[data_fetcher] Error fetching main location data: {e}")
        df = None

    # 🟨 2️⃣ Jika gagal → cari stasiun terdekat
    try:
        nearby_url = (
            f"https://air-quality-api.open-meteo.com/v1/locations?"
            f"latitude={lat}&longitude={lon}&radius={radius_km}"
        )
        nearby_res = requests.get(nearby_url, timeout=10)
        nearby_res.raise_for_status()
        nearby_data = nearby_res.json()

        if "results" in nearby_data and len(nearby_data["results"]) > 0:
            nearest = nearby_data["results"][0]
            nearest_lat = nearest["latitude"]
            nearest_lon = nearest["longitude"]
            nearest_name = nearest.get("name", "Unknown Station")

            print(f"[data_fetcher] Using nearest station: {nearest_name} "
                  f"({nearest_lat:.4f}, {nearest_lon:.4f})")

            df_nearest = fetch_data(nearest_lat, nearest_lon)
            if df_nearest is not None:
                return {
                    "data": df_nearest,
                    "location_name": f"Stasiun {nearest_name}",
                    "latitude": nearest_lat,
                    "longitude": nearest_lon,
                    "source": "Open-Meteo Air Quality API (Nearest Station)"
                }

        print("[data_fetcher] No nearby station found.")
        return None

    except requests.exceptions.RequestException as e:
        print(f"[data_fetcher] Error finding nearby station: {e}")
        return None

# ----------------------------
# Get latest measurements for a given location id
# ----------------------------
def get_latest_by_location_id(location_id: int, use_cache=True):
    url = f"{OPENAQ_API_BASE}/latest"
    params = {"locations_id": location_id}
    cache_name = f"latest_loc_{location_id}"
    resp = _request_json(url, params=params, use_cache=use_cache, cache_name=cache_name)
    if not resp:
        return None
    results = resp.get("results", [])
    if not results:
        return None
    # Flatten measurements to DataFrame
    measurements = results[0].get("measurements", [])
    df = pd.DataFrame(measurements)[["parameter", "value", "unit", "lastUpdated"]]
    # Add meta
    df["location_id"] = location_id
    df["location_name"] = results[0].get("location")
    coords = results[0].get("coordinates", {})
    df["latitude"] = coords.get("latitude")
    df["longitude"] = coords.get("longitude")
    return df


# ----------------------------
# Get latest aggregated for a city (choose first station or aggregate)
# ----------------------------
def get_latest_by_city(city: str, use_cache=True):
    df_locs = get_locations(city=city, use_cache=use_cache, limit=100)
    if df_locs is None or df_locs.empty:
        return None
    # pick the first location that has coordinates
    for _, row in df_locs.iterrows():
        if pd.notna(row["latitude"]) and pd.notna(row["longitude"]):
            loc_id = row["id"]
            return get_latest_by_location_id(loc_id, use_cache=use_cache)
    return None


# ----------------------------
# Get historical measurements for a location or by coords (date range)
# ----------------------------
def get_measurements_for_location(location_id: int, date_from: str, date_to: str, parameter: str = None, use_cache=True):
    url = f"{OPENAQ_API_BASE}/measurements"
    params = {
        "location_id": location_id,
        "date_from": date_from,
        "date_to": date_to,
        "limit": 10000,
        "page": 1
    }
    if parameter:
        params["parameter"] = parameter

    cache_name = f"measurements_loc_{location_id}_{date_from}_{date_to}_{parameter or 'all'}"
    resp = _request_json(url, params=params, use_cache=use_cache, cache_name=cache_name)
    if not resp:
        return None
    results = resp.get("results", [])
    if not results:
        return pd.DataFrame()
    df = pd.DataFrame(results)
    return df


def get_measurements_by_coords(lat: float, lon: float, radius_km: float = 10, date_from: str = None, date_to: str = None, parameter: str = None, use_cache=True):
    """
    Query measurements by coordinates (search nearby locations and fetch measurements).
    date_from / date_to in ISO format: "YYYY-MM-DDTHH:MM:SSZ" or "YYYY-MM-DD"
    """
    # 1) find locations near coords
    df_locs = get_locations(use_cache=use_cache, limit=500)
    if df_locs is None or df_locs.empty:
        return None

    # compute distance and filter
    df_locs = df_locs.dropna(subset=["latitude", "longitude"]).copy()
    df_locs["dist_km"] = df_locs.apply(lambda r: haversine(lon, lat, r["longitude"], r["latitude"]), axis=1)
    nearby = df_locs[df_locs["dist_km"] <= radius_km].sort_values("dist_km")
    if nearby.empty:
        # fallback: pick nearest irrespective of radius
        nearest = df_locs.sort_values("dist_km").iloc[0]
        nearby = pd.DataFrame([nearest])

    # For each nearby location, fetch measurements (limited)
    frames = []
    for idx, r in nearby.iterrows():
        loc_id = r["id"]
        dfm = get_measurements_for_location(loc_id, date_from=date_from, date_to=date_to, parameter=parameter, use_cache=use_cache)
        if dfm is not None and not dfm.empty:
            dfm["location_name"] = r["name"]
            dfm["dist_km"] = r["dist_km"]
            frames.append(dfm)
    if not frames:
        return pd.DataFrame()
    all_df = pd.concat(frames, ignore_index=True)
    return all_df


# ----------------------------
# Summarize measurements: produce daily averages per parameter
# ----------------------------
def summarize_measurements(meas_df: pd.DataFrame, freq="D"):
    """
    meas_df: DataFrame from get_measurements_for_location or get_measurements_by_coords
    freq: 'D' daily, 'W' weekly
    returns: pivot table with index=date and columns=parameter (mean values)
    """
    if meas_df is None or meas_df.empty:
        return pd.DataFrame()
    # try to standardize date column
    if "date" in meas_df.columns and isinstance(meas_df.loc[0, "date"], dict):
        # OpenAQ sometimes contains nested date object: date.utc
        meas_df["date_utc"] = meas_df["date"].apply(lambda x: x.get("utc") if isinstance(x, dict) else x)
    elif "date" in meas_df.columns:
        meas_df["date_utc"] = meas_df["date"]
    elif "lastUpdated" in meas_df.columns:
        meas_df["date_utc"] = meas_df["lastUpdated"]
    else:
        # attempt common fields
        meas_df["date_utc"] = meas_df.get("lastUpdated", pd.NaT)

    meas_df["date_utc"] = pd.to_datetime(meas_df["date_utc"])
    meas_df = meas_df.dropna(subset=["parameter", "value", "date_utc"])
    meas_df["date_trunc"] = meas_df["date_utc"].dt.floor(freq.lower() if freq=="D" else "W")
    pivot = meas_df.groupby(["date_trunc", "parameter"])["value"].mean().unstack(fill_value=None)
    pivot.index = pd.to_datetime(pivot.index)
    return pivot.sort_index()


# ----------------------------
# Example convenience wrapper
# ----------------------------
def fetch_and_summarize_by_coords(lat, lon, radius_km=10, days=7, parameter=None):
    date_to = datetime.utcnow()
    date_from = date_to - timedelta(days=days)
    date_to_s = date_to.strftime("%Y-%m-%dT%H:%M:%SZ")
    date_from_s = date_from.strftime("%Y-%m-%dT%H:%M:%SZ")

    meas = get_measurements_by_coords(lat=lat, lon=lon, radius_km=radius_km,
                                     date_from=date_from_s, date_to=date_to_s, parameter=parameter, use_cache=True)
    summary = summarize_measurements(meas, freq="D")
    return {"raw": meas, "summary": summary}


# ----------------------------
# If module is run directly, quick demo (for dev)
# ----------------------------
if __name__ == "__main__":
    print("Demo: get locations for Indonesia (first 10)")
    df_loc = get_locations(country="ID", limit=50)
    if df_loc is not None:
        print(df_loc.head(10).to_string(index=False))
    else:
        print("No locations found.")

    # quick sample: Jakarta latest
    print("\nLatest Jakarta sample:")
    df_latest = get_latest_by_city("Jakarta")
    if df_latest is not None:
        print(df_latest.to_string(index=False))
    else:
        print("No latest data for Jakarta.")
