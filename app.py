import streamlit as st
from streamlit_folium import st_folium
from agents import data_fetcher
from utils import map_utils, visualization

# 🧭 Konfigurasi halaman
st.set_page_config(page_title="EnvironPolicy Insight 🌿", layout="wide")
st.title("🌍 Air Quality Monitor")

# 1️⃣ Inisialisasi session state
if "api_result" not in st.session_state:
    st.session_state.api_result = None
if "last_processed_coords" not in st.session_state:
    st.session_state.last_processed_coords = None

# 2️⃣ Buat peta dari utils
m = map_utils.make_map(st.session_state.last_processed_coords or [-2.5, 118])

if st.session_state.api_result:
    map_utils.add_markers(m, st.session_state.last_processed_coords, st.session_state.api_result)

map_data = st_folium(
    m, 
    width=1500, 
    height=500, 
    key=f"map_{st.session_state.last_processed_coords}",
    returned_objects=["last_clicked"]
)

# 3️⃣ Handle klik baru di peta
if map_data and map_data["last_clicked"]:
    clicked_coords = (
        map_data["last_clicked"]["lat"],
        map_data["last_clicked"]["lng"]
    )

    # hanya proses jika klik baru
    if clicked_coords != st.session_state.last_processed_coords:
        lat, lon = clicked_coords
        with st.spinner(f"Mengambil data untuk ({lat:.4f}, {lon:.4f})..."):
            result = data_fetcher.get_air_quality_by_coords(lat, lon)

        # simpan hasilnya di session state
        st.session_state.api_result = result
        st.session_state.last_processed_coords = clicked_coords

        # rerun untuk render ulang dengan peta dan data baru
        st.rerun()

# 4️⃣ Tampilkan hasil data dan grafik
if st.session_state.api_result:
    result = st.session_state.api_result
    if result and "data" in result:
        df = result["data"]
        city = result["location_name"]
        src = result["source"]
        loc_lat = result["latitude"]
        loc_lon = result["longitude"]

        st.success(f"📍 Menampilkan data untuk: {city} ({loc_lat:.4f}, {loc_lon:.4f})")
        st.caption(f"🗺️ Sumber data: {src}")
        st.subheader("📊 Data Kualitas Udara (10 data terbaru)")
        st.dataframe(df.head(10))

        visualization.display_air_quality_charts(df)
    else:
        st.warning("❌ Tidak ada data kualitas udara untuk lokasi ini atau stasiun terdekat.")
else:
    st.info("Klik pada peta untuk memilih lokasi yang ingin dicek 🌎.")
