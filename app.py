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
from datetime import date

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
            today_str = str(date.today()) # Ambil tanggal hari ini (misal: 2025-11-30)
            print(today_str)
            with st.spinner("Menganalisis maksud pertanyaan..."):
                loc_intent = geo_agent.extract_location_from_query(user_prompt, current_date=today_str)
                print(loc_intent)

            # Ambil hasil deteksi tanggal dari AI
            date_range = loc_intent.get("date_range", {})
            req_start = date_range.get("start")
            req_end = date_range.get("end")
            
            # Tampilkan info ke user tanggal berapa yang sedang dilihat
            if req_start == req_end:
                 st.info(f"📅 Menampilkan data untuk tanggal: **{req_start}**")
            else:
                 st.info(f"📅 Menampilkan data periode: **{req_start}** s.d **{req_end}**")

            # === CASE A: User meminta Lokasi Baru (Single/Multi) ===
            # Hanya proses jika intent adalah "single", "subareas", atau "multi"
            # Jika intent adalah "none", skip ke CASE B (pertanyaan konteks)
            
            # ---------------------------------------------------------
            # 1. LOGIKA FETCHING PINTAR (TIME-AWARE & NAME-LOCKING)
            # ---------------------------------------------------------
            should_fetch = False
            is_date_change = False
            
            # Cek 1: Lokasi Baru
            if loc_intent.get("intent") in ["single", "subareas", "multi"]:
                should_fetch = True
            
            # Cek 2: Ganti Tanggal (Lokasi Sama)
            elif loc_intent.get("intent") == "none" and st.session_state.api_result:
                if req_start != str(date.today()): 
                     should_fetch = True
                     is_date_change = True
                     # Ambil koordinat terakhir dari memori
                     last_lat, last_lon = st.session_state.last_processed_coords
                     
                     # === NAME LOCKING: Simpan nama lama agar tidak hilang ===
                     locked_name = st.session_state.api_result.get("location_name", "Lokasi Terpilih")
                     
                     # Siapkan list koordinat manual (Bypass Geocoder)
                     coords_list = [(locked_name, last_lat, last_lon)]

            # Eksekusi Fetching
            if should_fetch:
                # Tentukan nama area untuk loading message
                if is_date_change:
                     st.info(f"🔄 Mengambil data {req_start} untuk **{locked_name}**...")
                     # PENTING: Jangan panggil geo_agent saat ganti tanggal!
                     # Kita sudah punya 'coords_list' yang benar di atas.
                else:
                     # Logika lama untuk lokasi baru
                     area_label = loc_intent.get("parent_area") or loc_intent.get("areas", ["Area"])[0]
                     st.info(f"🔍 Mencari data wilayah: {area_label}...")
                     
                     # Panggil Geocoder HANYA jika bukan ganti tanggal
                     coords_list = geo_agent.get_coordinates_for_area(
                        user_query=user_prompt,
                        area_name=area_label,
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
                            res = data_fetcher.get_air_quality_by_coords(
                            lat, lon, 
                            start_date=req_start, 
                            end_date=req_end)

                            # === NAME INJECTION: Kembalikan nama yang terkunci ===
                            if is_date_change:
                                res["location_name"] = locked_name
                                name = locked_name 
                            # ===================================================

                            if res is None or "data" not in res:
                                print(f"⚠️ Gagal mengambil data untuk {name}, skipping...")
                                prog_bar.progress((i + 1) / len(coords_list))
                                continue  # Lanjut ke kota berikutnya
        
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

                            st.session_state.multi_area_results.append({
                                        "name": name, "lat": lat, "lon": lon, 
                                        "data": res["data"], "summary": s_dict
                                    })
                            prog_bar.progress((i + 1) / len(coords_list))
                                    
                    else:
                        
                        # Ambil tuple pertama: (name, lat, lon)
                        name, lat, lon = coords_list[0]
                        
                        res = data_fetcher.get_air_quality_by_coords(
                        lat, lon, 
                        start_date=req_start, 
                        end_date=req_end)
                        
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
                                # === PERBAIKAN DI SINI ===
                                # Kita ambil nama kotanya
                                loc_name = full_res["name"]
                                
                                # Convert data angka ke JSON
                                raw_json = full_res["data"].tail(24).to_json(orient="records")
                                
                                # KITA TEMPEL LABELNYA SECARA MANUAL
                                final_context = f"""
                                LOKASI: {loc_name}
                                SUMBER DATA: Open-Meteo Air Quality API
                                DATA SENSOR (24 Jam Terakhir):
                                {raw_json}
                                """
                                
                                # Kirim final_context (yang ada labelnya), BUKAN raw_json
                                # response_text = aq_agent.analyze_air_quality(user_prompt, final_context)
                                pass

                        else:
                            # Multi Area Analysis (Bandingkan banyak kota)
                            st.session_state.last_processed_coords = [coords_list[0][1], coords_list[0][2]] # Center ke kota pertama
                            with st.spinner("Membandingkan antar lokasi..."):
                                response_text = aq_agent.compare_multi_area_quality(loc_intent, summary_data, user_prompt)
                    else:
                        area_name = loc_intent.get("parent_area") or loc_intent.get("areas", ["lokasi ini"])[0]
                        response_text = (
                            f"⚠️ **Data Tidak Ditemukan:**\n"
                            f"Sistem berhasil menemukan lokasi **{area_name}**, namun gagal mengambil data kualitas udara terkini dari server.\n\n"
                            f"Kemungkinan penyebab:\n"
                            f"- Gangguan koneksi ke API Open-Meteo.\n"
                            f"- Data sensor PM2.5 tidak tersedia untuk koordinat tersebut saat ini."
                        )    

            # === CASE B: Pertanyaan Konteks (Tentang data yang sedang tampil) ===
            else:
                current_context = ""
                location_label = "Lokasi Terpilih"
                
                # === [PERUBAHAN 2] SMART SLICING (Mencegah Salah Baca Tanggal) ===
                def get_data_for_date(df, target_date):
                    """Ambil data HANYA untuk tanggal yang diminta user"""
                    try:
                        # Pastikan kolom time formatnya datetime
                        df['time'] = pd.to_datetime(df['time'])
                        # Buat kolom bantu string tanggal (YYYY-MM-DD)
                        df['date_str'] = df['time'].dt.strftime('%Y-%m-%d')
                        
                        # FILTER: Ambil baris yang tanggalnya sama dengan target_date
                        filtered = df[df['date_str'] == target_date]
                        
                        # Fallback: Jika kosong (misal beda timezone), ambil 24 jam terakhir
                        if filtered.empty:
                            return df.tail(24)
                        return filtered
                    except Exception:
                        return df.tail(24)

                if st.session_state.api_result:
                    # Konteks Single Point
                    full_data = st.session_state.api_result["data"]
                    location_label = st.session_state.api_result.get("location_name", "Lokasi")
                    
                    # POTONG DATA SESUAI TANGGAL REQUEST (req_start)
                    # Bukan asal .tail(24) lagi
                    relevant_data = get_data_for_date(full_data, req_start)
                    
                    raw_json = relevant_data.to_json(orient="records")
                    
                    # Tambahkan Header Tanggal agar LLM sadar konteks waktu
                    current_context = (
                        f"LOKASI: {location_label}\n"
                        f"TANGGAL DATA: {req_start}\n" # <--- Jangkar Waktu
                        f"DATA SENSOR:\n{raw_json}"
                    )
                    
                elif st.session_state.multi_area_results:
                    # Konteks Multi Area
                    raw_json = json.dumps([item["summary"] for item in st.session_state.multi_area_results])
                    current_context = f"LOKASI: Perbandingan Multi-Area\nTANGGAL: {req_start}\nDATA:\n{raw_json}"
                
                
                if current_context:
                    with st.spinner("Menganalisis konteks data..."):
                        response_text = aq_agent.analyze_air_quality(user_prompt, current_context)
                else:
                    response_text = aq_agent.analyze_air_quality(user_prompt, "Tidak ada data real-time.")
            

            # ---------------------------------------------------------
            # 2. CONTEXT BUILDING (FORMAT TANGGAL YANG BISA DIBACA LLM)
            # ---------------------------------------------------------
            
            # (Pastikan ini dijalankan setiap kali, baik fetch baru maupun tidak)
            if not response_text: # Jika belum ada error
                current_context = ""
                
                # Fungsi Helper: Filter Tanggal & Format JSON Manusiawi
                def get_clean_json(df, target_date):
                    try:
                        df['time'] = pd.to_datetime(df['time'])
                        df['date_str'] = df['time'].dt.strftime('%Y-%m-%d')
                        
                        # Filter sesuai tanggal request
                        filtered = df[df['date_str'] == target_date]
                        if filtered.empty: filtered = df.tail(24)
                        
                        # === KUNCI UTAMA: date_format='iso' ===
                        # Ini mengubah 1733356800000 menjadi "2025-12-05T07:00:00"
                        return filtered.to_json(orient="records", date_format="iso")
                    except:
                        return df.tail(24).to_json(orient="records", date_format="iso")

                if st.session_state.api_result:
                    # Single Point Context
                    full_res = st.session_state.api_result
                    raw_json = get_clean_json(full_res["data"], req_start)
                    
                    current_context = (
                        f"LOKASI: {full_res['location_name']}\n"
                        f"TANGGAL TARGET: {req_start}\n"
                        f"DATA SENSOR (Format ISO Date):\n{raw_json}"
                    )
                    
                    # Kirim ke LLM
                    with st.spinner("Menganalisis data..."):
                        print("DEBUG JSON TO LLM:", raw_json) # Cek terminal: Apakah isinya [] atau data penuh?
                        response_text = aq_agent.analyze_air_quality(user_prompt, current_context)

                elif st.session_state.multi_area_results:
                     # Multi Area Context
                     # ... (Logika multi area sama, pastikan format json string aman) ...
                     with st.spinner("Menganalisis perbandingan..."):
                        response_text = aq_agent.compare_multi_area_quality(loc_intent, summary_data, user_prompt)

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

            today_str = str(date.today())

            with st.spinner(f"Mengambil data udara untuk ({lat:.4f}, {lon:.4f})..."):
                result = data_fetcher.get_air_quality_by_coords(
                    lat, lon, 
                    start_date=today_str, 
                    end_date=today_str
                )
            
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
            
            st.subheader("📊 Data Lengkap")
            
            # ---------------------------------------------------------
            # FITUR PAGINATION (Halaman per 10 baris)
            # ---------------------------------------------------------
            
            # 1. Urutkan dari yang TERBARU (Opsional, tapi disarankan untuk monitoring)
            # Agar Page 1 berisi data hari ini/besok, bukan data tahun lalu.
            if 'time' in df.columns:
                df_sorted = df.sort_values(by='time', ascending=True).reset_index(drop=True)
            else:
                df_sorted = df

            # 2. Konfigurasi Halaman
            ROWS_PER_PAGE = 10
            total_rows = len(df_sorted)
            total_pages = (total_rows - 1) // ROWS_PER_PAGE + 1
            
            # Inisialisasi state halaman jika belum ada
            if "current_page" not in st.session_state:
                st.session_state.current_page = 1
                
            # Validasi agar halaman tidak "offside" saat data berubah
            if st.session_state.current_page > total_pages:
                st.session_state.current_page = total_pages
            if st.session_state.current_page < 1:
                st.session_state.current_page = 1

            # 3. Kontrol Navigasi (Tombol Previous & Next)
            # Kita bagi kolom agar tombolnya rapi di tengah
            c1, c2, c3, c4, c5 = st.columns([0.5, 1, 2, 1, 0.5])
            
            with c2:
                # Tombol Prev (Mundur)
                if st.button("◀️ Mundur", key="prev_btn", disabled=(st.session_state.current_page == 1)):
                    st.session_state.current_page -= 1
                    st.rerun()
            
            with c4:
                # Tombol Next (Maju)
                if st.button("Maju ▶️", key="next_btn", disabled=(st.session_state.current_page == total_pages)):
                    st.session_state.current_page += 1
                    st.rerun()
            
            with c3:
                # Info Halaman
                st.markdown(f"<div style='text-align: center; padding-top: 5px;'>Halaman <b>{st.session_state.current_page}</b> dari {total_pages}</div>", unsafe_allow_html=True)

            # 4. Potong Data (Slicing) & Tampilkan
            start_idx = (st.session_state.current_page - 1) * ROWS_PER_PAGE
            end_idx = start_idx + ROWS_PER_PAGE
            
            # Tampilkan slice data
            st.dataframe(df_sorted.iloc[start_idx:end_idx], use_container_width=True)
            st.caption(f"Menampilkan baris {start_idx+1} s.d {min(end_idx, total_rows)} dari total {total_rows} data.")
            # ---------------------------------------------------------

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