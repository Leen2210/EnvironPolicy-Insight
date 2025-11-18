import streamlit as st
from streamlit_folium import st_folium
from agents import data_fetcher
from utils import map_utils, visualization

import google.generativeai as genai

from dotenv import load_dotenv
import os

load_dotenv()

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.5-flash")

# ==== LOAD WHO GUIDELINES PDF =====
import os

WHO_PDF_PATH = "WHO_Global_Air_Quality_Guidelines.pdf"

if os.path.exists(WHO_PDF_PATH):
    who_pdf = genai.upload_file(WHO_PDF_PATH)
else:
    st.warning("⚠️ PDF WHO Guidelines tidak ditemukan! Pastikan file berada di folder yang sama dengan app.py.")


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
        st.subheader("📊 Data Kualitas Udara (Seluruh data terbaru)")
        st.dataframe(df) # set data yg ditampilkan head/tail

        visualization.display_air_quality_charts(df)

        # ============================
        # 5️⃣ Chatbot Interaktif (Gemini)
        # ============================

        st.subheader("🤖 Chatbot Analisis Udara (Gemini)")

        # Siapkan chat history
        if "chat_history" not in st.session_state:
            st.session_state.chat_history = []

        # Tampilkan history sebelumnya
        for msg in st.session_state.chat_history:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])


        # ---- User Input ----
        user_prompt = st.chat_input("Tanyakan apapun tentang kualitas udara...")

        if user_prompt:

            # Simpan pesan user
            st.session_state.chat_history.append({"role": "user", "content": user_prompt})

            # Semua data udara sebagai JSON
            df_json = df.to_json(orient="records")

            # System prompt
            system_prompt = f"""
            Kamu adalah AI analis kualitas udara.

            Berikut adalah seluruh data kualitas udara terbaru (format JSON):
            {df_json}

            Gunakan isi PDF WHO Global Air Quality Guidelines untuk:
            - membandingkan apakah nilai polutan melebihi batas WHO
            - memberi rekomendasi kesehatan
            - menjelaskan standar PM2.5, PM10, O3, CO, NO2, SO2

            Jika suatu nilai tidak tersedia (NaN), sampaikan dengan sopan.
            """

            # === Call Gemini with PDF as input ===
            if who_pdf:
                response = model.generate_content(
                    [system_prompt, user_prompt, who_pdf]
                )
            else:
                response = model.generate_content(
                    system_prompt + "\n\nPertanyaan:\n" + user_prompt
                )

            answer = response.text.strip()

            # Show chat reply
            with st.chat_message("assistant"):
                st.write(answer)

            st.session_state.chat_history.append({"role": "assistant", "content": answer})


    else:
        st.warning("❌ Tidak ada data kualitas udara untuk lokasi ini atau stasiun terdekat.")
else:
    st.info("Klik pada peta untuk memilih lokasi yang ingin dicek 🌎.")
