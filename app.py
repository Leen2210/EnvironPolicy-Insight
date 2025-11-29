import streamlit as st
from streamlit_folium import st_folium
from agents import data_fetcher
from agents.evaluator import AirQualityAgent  # Import Agent baru
from agents.geocoder import GeocoderAgent
from utils import map_utils, visualization
from dotenv import load_dotenv
import os
import pandas as pd
import json

load_dotenv()

# 🧭 Konfigurasi halaman
st.set_page_config(page_title="EnvironPolicy Insight 🌿", layout="wide")
st.title("🌍 Air Quality Monitor & Advisor")

# ==== SETUP AGENT & RAG (Hanya berjalan sekali berkat caching) ====
@st.cache_resource
def setup_agent():
    api_key = os.getenv('GEMINI_API_KEY')
    pdf_path = "WHO_Global_Air_Quality_Guidelines.pdf"
    
    if not api_key:
        st.error("API Key Gemini tidak ditemukan.")
        return None, None

    agent = AirQualityAgent(api_key, pdf_path)
    geo_agent = GeocoderAgent(api_key) # ###########BARU##########
    
    # Inisialisasi Knowledge Base (Indexing PDF)
    with st.spinner("Membangun basis pengetahuan dari WHO Guidelines..."):
        success, msg = agent.initialize_knowledge_base()
    
    if success:
        print("Agent ready.")
    else:
        st.error(msg)
    
    return agent, geo_agent

# Inisialisasi agent
aq_agent, geo_agent = setup_agent()

# 1️⃣ Inisialisasi session state
if "api_result" not in st.session_state:
    st.session_state.api_result = None
if "multi_area_results" not in st.session_state:
    st.session_state.multi_area_results = [] 
if "last_processed_coords" not in st.session_state:
    st.session_state.last_processed_coords = [-2.5, 118]
if "chat_history" not in st.session_state:
    st.session_state.chat_history = [{"role": "assistant", "content": "Halo! Tanyakan kondisi udara di kota mana saja (misal: 'Bagaimana udara di Jawa Barat?' atau 'Cek Jakarta')."}]

col_map, col_chat = st.columns([1.8, 1.2])



# ============================
# KANAN: CHATBOT INTERAKTIF
# ============================

with col_chat:
    st.subheader("🤖 AI Consultant")
    st.caption("Tanyakan analisis berdasarkan data & WHO Guidelines.")

    # Container untuk chat history agar bisa discroll
    chat_container = st.container(height=600)

    # Tampilkan history
    with chat_container:
        for msg in st.session_state.chat_history:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])

    # Input User
    if user_prompt := st.chat_input("Ketik pertanyaan atau nama lokasi..."):
        
        # 1. Tampilkan pesan user
        with chat_container:
            with st.chat_message("user"):
                st.write(user_prompt)
        
        st.session_state.chat_history.append({"role": "user", "content": user_prompt})

        # 2. Proses dengan Agent (Intention Detection & RAG)
        if aq_agent and geo_agent:
            response_text = ""
            
            loc_intent = None
            with st.spinner("Menganalisis maksud pertanyaan..."):
                loc_intent = geo_agent.extract_location_from_query(user_prompt)
                print(loc_intent)

            # === CASE A: User meminta Lokasi Baru (Single/Multi) ===
            # Hanya proses jika intent adalah "single", "subareas", atau "multi"
            # Jika intent adalah "none", skip ke CASE B (pertanyaan konteks)
            if loc_intent and loc_intent.get("intent") in ["single", "subareas", "multi"]:
                status_msg = st.empty()
                area_label = None

                if "parent_area" in loc_intent and loc_intent["parent_area"]:
                    area_label = loc_intent["parent_area"]
                else:
                    # kalau areas ada dan tidak kosong
                    areas = loc_intent.get("areas", [])
                    area_label = areas[0] if areas else "Area Tidak Diketahui"

                status_msg.info(f"🔍 Mencari data wilayah: {area_label}...")
                
                # Geocoding (Bisa return 1 atau banyak koordinat)
                area_to_process = loc_intent.get("parent_area") or loc_intent.get("areas", [""])[0]
                
                # Panggil dengan data intent lengkap
                coords_list = geo_agent.get_coordinates_for_area(
                    user_query=user_prompt,
                    area_name=area_to_process,
                    intent_data=loc_intent
                )
                print(coords_list)
                
                if not coords_list:
                    response_text = f"Maaf, tidak ditemukan data lokasi untuk '{loc_intent}'."
                else:
                    # Reset state data lama
                    st.session_state.api_result = None
                    st.session_state.multi_area_results = []
                    
                    # Fetch Data Loop
                    summary_data = []
                    prog_bar = st.progress(0)
                    
                    if len(coords_list) > 1:
                        for i, (name, lat, lon) in enumerate(coords_list):
                            # Fetch data udara
                            res = data_fetcher.get_air_quality_by_coords(lat, lon)
        
                            # Ambil snapshot terakhir untuk Summary
                            valid_data = res["data"].dropna(subset=['pm2_5'])
                            latest = valid_data.iloc[-1]
                            s_dict = {
                                        "city": name,
                                        "pm2_5": float(latest.get("pm2_5", 0)),
                                        "pm10": float(latest.get("pm10", 0)),
                                        "no2": float(latest.get("nitrogen_dioxide", 0)),
                                        "so2": float(latest.get("sulphur_dioxide", 0)),
                                        "ozone": float(latest.get("ozone", 0)),
                                        "co": float(latest.get("carbon_monoxide", 0))
                                    }
                            summary_data.append(s_dict)
                                    # Simpan data lengkap untuk marker di peta
                            st.session_state.multi_area_results.append({
                                        "name": name, "lat": lat, "lon": lon, 
                                        "data": res["data"], "summary": s_dict
                                    })
                            prog_bar.progress((i + 1) / len(coords_list))
                                    
                    else:
                        
                        # Ambil tuple pertama: (name, lat, lon)
                        name, lat, lon = coords_list[0]
                        
                        res = data_fetcher.get_air_quality_by_coords(lat, lon)
                        
                        if res and "data" in res:
                            res["data"] = res["data"].dropna(subset=['pm2_5'])
                            
                            # Simpan ke state api_result (untuk chart detail)
                            st.session_state.api_result = res
                            st.session_state.multi_area_results = []

                            # Siapkan summary data agar konsisten (List of Dict)
                            if not res["data"].empty:
                                latest = res["data"].iloc[-1]
                                s_dict = {
                                    "city": name,
                                    "pm2_5": float(latest.get("pm2_5", 0)),
                                    "pm10": float(latest.get("pm10", 0)),
                                    "no2": float(latest.get("nitrogen_dioxide", 0)),
                                    "so2": float(latest.get("sulphur_dioxide", 0)),
                                    "ozone": float(latest.get("ozone", 0)),
                                    "co": float(latest.get("carbon_monoxide", 0))
                                }
                                summary_data.append(s_dict)

                            
                                st.session_state.multi_area_results.append({
                                    "name": name, "lat": lat, "lon": lon,
                                    "data": res["data"], "summary": s_dict
                                })
                    
                    prog_bar.empty()
                    status_msg.empty()

                    # Analisis Hasil
                    if summary_data:
                        # Jika hasil cuma 1 (Single Point via Chat), set api_result juga agar grafik detail muncul
                        if len(summary_data) == 1:
                            full_res = st.session_state.multi_area_results[0]
                            st.session_state.api_result = {
                                "data": full_res["data"],
                                "location_name": full_res["name"],
                                "latitude": full_res["lat"],
                                "longitude": full_res["lon"],
                                "source": "Auto-Search"
                            }
                            # Update peta center
                            st.session_state.last_processed_coords = [full_res["lat"], full_res["lon"]]
                            
                            # Analisis Single Location
                            with st.spinner("Menganalisis satu lokasi..."):
                                latest_json = full_res["data"].tail(24).to_json(orient="records")
                                response_text = aq_agent.analyze_air_quality(user_prompt, latest_json)
                                # print(latest_json)

                        else:
                            # Multi Area Analysis (Bandingkan banyak kota)
                            st.session_state.last_processed_coords = [coords_list[0][1], coords_list[0][2]] # Center ke kota pertama
                            with st.spinner("Membandingkan antar lokasi..."):
                                response_text = aq_agent.compare_multi_area_quality(loc_intent, summary_data, user_prompt)
                    else:
                        response_text = f"Data kualitas udara tidak tersedia untuk {loc_intent} saat ini."
    

            # === CASE B: Pertanyaan Konteks (Tentang data yang sedang tampil) ===
            else:
                current_context = ""
                if st.session_state.api_result:
                    # Konteks Single Point
                    df = st.session_state.api_result["data"]
                    current_context = df.tail(24).to_json(orient="records")
                elif st.session_state.multi_area_results:
                    # Konteks Multi Area Summary
                    current_context = json.dumps([item["summary"] for item in st.session_state.multi_area_results])
                
                if current_context:
                    with st.spinner("Menganalisis konteks data..."):
                        response_text = aq_agent.analyze_air_quality(user_prompt, current_context)
                else:
                    response_text = aq_agent.analyze_air_quality(user_prompt, "Tidak ada data real-time.")
            
            # 3. Tampilkan balasan
            with chat_container:
                with st.chat_message("assistant"):
                    st.write(response_text)
            
            st.session_state.chat_history.append({"role": "assistant", "content": response_text})
            st.rerun() # Rerun untuk update peta di sebelah kiri
        else:
            st.error("Agent belum siap. Cek koneksi atau API Key.")



# ============================
# KIRI: PETA & VISUALISASI
# ============================
with col_map:
    # 2️⃣ Buat peta dari utils
    current_coords = st.session_state.last_processed_coords
    m = map_utils.make_map(current_coords)

    if st.session_state.multi_area_results:
        all_lats = []
        all_lons = []
        for item in st.session_state.multi_area_results:
            all_lats.append(item["lat"])
            all_lons.append(item["lon"])
            # Format data sesuai utilitas peta
            temp_res = {
                "latitude": item["lat"],
                "longitude": item["lon"],
                "location_name": item["name"],
                "data": item["data"],
                "source": "Open-Meteo (Multi-Area)"
            }
            map_utils.add_markers(m, (item["lat"], item["lon"]), temp_res)
        
        # Jika ada lebih dari 1 titik, atur peta agar memuat semua titik (zoom out otomatis)
        if len(st.session_state.multi_area_results) > 1:
            min_lat, max_lat = min(all_lats), max(all_lats)
            min_lon, max_lon = min(all_lons), max(all_lons)
            # Fit bounds: [SouthWest, NorthEast]
            m.fit_bounds([[min_lat, min_lon], [max_lat, max_lon]])

    
    # Render Single Marker (jika ada dan bukan mode multi view)
    elif st.session_state.api_result:
        map_utils.add_markers(m, st.session_state.last_processed_coords, st.session_state.api_result)

    map_data = st_folium(
        m, 
        width=1500, 
        height=500, 
        key=f"map_widget",
        returned_objects=["last_clicked"]
    )

    # 3️⃣ Handle klik baru di peta
    if map_data and map_data["last_clicked"]:
        clicked_coords = (
            map_data["last_clicked"]["lat"],
            map_data["last_clicked"]["lng"]
        )

        # Cek apakah koordinat berbeda signifikan untuk menghindari reload loop
        prev_lat, prev_lon = st.session_state.last_processed_coords
        if abs(clicked_coords[0] - prev_lat) > 0.0001 or abs(clicked_coords[1] - prev_lon) > 0.0001:
            
            lat, lon = clicked_coords
            with st.spinner(f"Mengambil data udara untuk ({lat:.4f}, {lon:.4f})..."):
                result = data_fetcher.get_air_quality_by_coords(lat, lon)
            
            # Pastikan result adalah dict dan ada data
            if result and "data" in result:
                # Bersihkan data dari NaN
                result["data"] = result["data"].dropna(subset=['pm2_5'])
                # Simpan state dengan struktur dict yang benar
                st.session_state.api_result = result
            else:
                st.session_state.api_result = None
            # Reset mode multi-area agar fokus ke single point
            st.session_state.multi_area_results = [] 
            st.session_state.last_processed_coords = clicked_coords
            
            #Tambahkan notifikasi ke chat
            location_name = result.get('location_name', 'Koordinat Baru') if result and isinstance(result, dict) else 'Koordinat Baru'
            st.session_state.chat_history.append({
                "role": "assistant", 
                "content": f"✅ Data diperbarui manual dari peta: {location_name}"
            })
            st.rerun()


    # 4️⃣ Tampilkan hasil data dan grafik
    st.markdown("---")
    
    if st.session_state.api_result:
        # === TAMPILAN SINGLE DETAIL ===
        result = st.session_state.api_result
        if result and "data" in result:
            df = result["data"]
            city = result["location_name"]
            src = result["source"]
            
            st.success(f"📍 Lokasi: {city} ({result['latitude']:.4f}, {result['longitude']:.4f})")
            st.caption(f"🗺️ Sumber: {src}")
            
            st.subheader("📊 Data Terkini")
            st.dataframe(df.tail(5), use_container_width=True)
            
            visualization.display_air_quality_charts(df)
        else:
            st.warning("❌ Tidak ada data kualitas udara untuk lokasi ini.")


    elif st.session_state.multi_area_results:
        st.subheader("📊 Ringkasan Area")
        summary_list = [item["summary"] for item in st.session_state.multi_area_results]
        df_sum = pd.DataFrame(summary_list)
        
        if not df_sum.empty:
            # Rename kolom untuk display yang lebih baik
            display_columns = {
                'city': 'Kota',
                'pm2_5': 'PM2.5 (µg/m³)',
                'pm10': 'PM10 (µg/m³)',
                'no2': 'NO₂ (µg/m³)',
                'so2': 'SO₂ (µg/m³)',
                'ozone': 'Ozone (µg/m³)',
                'co': 'CO (µg/m³)'
            }
            df_display = df_sum.rename(columns=display_columns)
            
            # Highlight semua parameter dengan warna
            numeric_cols = [col for col in df_display.columns if col != 'Kota']
            st.dataframe(
                df_display.style.background_gradient(subset=numeric_cols, cmap='RdYlGn_r'),
                use_container_width=True
            )
            
            # Tampilkan grafik perbandingan
            visualization.display_multi_area_comparison(st.session_state.multi_area_results)
 
    
    else:
        st.info("👈 Klik peta atau ketik nama kota di kolom chat untuk memulai analisis.")