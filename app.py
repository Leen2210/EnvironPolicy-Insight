import streamlit as st
from streamlit_folium import st_folium
from agents import data_fetcher
from agents.evaluator import AirQualityAgent  # Import Agent baru
from utils import map_utils, visualization
from dotenv import load_dotenv
import os

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
        return None

    agent = AirQualityAgent(api_key, pdf_path)
    
    # Inisialisasi Knowledge Base (Indexing PDF)
    with st.spinner("Membangun basis pengetahuan dari WHO Guidelines..."):
        success, msg = agent.initialize_knowledge_base()
    
    if success:
        print("Agent ready.")
    else:
        st.error(msg)
    
    return agent

# Inisialisasi agent
aq_agent = setup_agent()

# 1️⃣ Inisialisasi session state
if "api_result" not in st.session_state:
    st.session_state.api_result = None
if "last_processed_coords" not in st.session_state:
    st.session_state.last_processed_coords = None
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# 2️⃣ Buat peta dari utils
# Default coords (Indonesia center roughly)
default_coords = [-2.5, 118]
current_coords = st.session_state.last_processed_coords or default_coords

m = map_utils.make_map(current_coords)

if st.session_state.api_result:
    map_utils.add_markers(m, st.session_state.last_processed_coords, st.session_state.api_result)

map_data = st_folium(
    m, 
    width=1500, 
    height=500, 
    key=f"map_widget", # Fixed key to prevent remounting issues
    returned_objects=["last_clicked"]
)

# 3️⃣ Handle klik baru di peta
if map_data and map_data["last_clicked"]:
    clicked_coords = (
        map_data["last_clicked"]["lat"],
        map_data["last_clicked"]["lng"]
    )

    # Cek apakah koordinat berbeda signifikan untuk menghindari reload loop
    if st.session_state.last_processed_coords != clicked_coords:
        lat, lon = clicked_coords
        with st.spinner(f"Mengambil data udara untuk ({lat:.4f}, {lon:.4f})..."):
            result = data_fetcher.get_air_quality_by_coords(lat, lon)

        # Simpan state
        st.session_state.api_result = result
        st.session_state.last_processed_coords = clicked_coords
        st.rerun()

# 4️⃣ Tampilkan hasil data dan grafik
if st.session_state.api_result:
    result = st.session_state.api_result
    if result and "data" in result:
        df = result["data"]
        city = result["location_name"]
        src = result["source"]
        
        # Layout kolom untuk data dan chat
        col1, col2 = st.columns([2, 1])

        with col1:
            st.success(f"📍 Lokasi: {city} ({result['latitude']:.4f}, {result['longitude']:.4f})")
            st.caption(f"🗺️ Sumber: {src}")
            
            # Tampilkan Dataframe (tail untuk data terbaru)
            st.subheader("📊 Data Terkini")
            st.dataframe(df.tail(5), use_container_width=True)
            
            # Visualisasi
            visualization.display_air_quality_charts(df)

        # ============================
        # 5️⃣ Chatbot Interaktif (RAG Enabled)
        # ============================
        with col2:
            st.subheader("🤖 AI Consultant")
            st.caption("Tanyakan analisis berdasarkan data di samping & WHO Guidelines.")

            # Container untuk chat history agar bisa discroll
            chat_container = st.container(height=500)

            # Tampilkan history
            with chat_container:
                for msg in st.session_state.chat_history:
                    with st.chat_message(msg["role"]):
                        st.write(msg["content"])

            # Input User
            if user_prompt := st.chat_input("Contoh: Apakah PM2.5 ini berbahaya bagi anak-anak?"):
                
                # 1. Tampilkan pesan user
                with chat_container:
                    with st.chat_message("user"):
                        st.write(user_prompt)
                
                st.session_state.chat_history.append({"role": "user", "content": user_prompt})

                # 2. Proses dengan Agent (RAG)
                if aq_agent:
                    with st.spinner("Menganalisis data & membaca panduan WHO..."):
                        # Ambil data terakhir (misal rata-rata 24 jam terakhir atau jam terakhir)
                        # Kita kirim summary data agar tidak terlalu besar
                        latest_data = df.tail(24).to_json(orient="records", date_format="iso")
                        
                        response_text = aq_agent.analyze_air_quality(user_prompt, latest_data)
                    
                    # 3. Tampilkan balasan
                    with chat_container:
                        with st.chat_message("assistant"):
                            st.write(response_text)
                    
                    st.session_state.chat_history.append({"role": "assistant", "content": response_text})
                else:
                    st.error("Agent belum siap. Cek koneksi atau API Key.")

    else:
        st.warning("❌ Tidak ada data kualitas udara untuk lokasi ini.")
else:
    st.info("👈 Silakan klik lokasi pada peta di atas untuk memulai analisis.")