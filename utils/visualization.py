import streamlit as st
import pandas as pd

def display_air_quality_charts(df):
    chart_cols = [col for col in ["pm2_5", "pm10"] if col in df.columns]
    if not chart_cols:
        st.info("Tidak ada kolom PM2.5 atau PM10 untuk divisualisasikan.")
        return
    st.subheader("📈 Tren PM2.5 dan PM10")
    st.line_chart(df.set_index("time")[chart_cols])

def display_multi_area_comparison(multi_area_results):
    """
    Menampilkan grafik perbandingan semua parameter kualitas udara untuk multi-area.
    Menggunakan line chart seperti single point untuk menampilkan tren waktu.
    
    Args:
        multi_area_results: List of dict dengan keys: name, lat, lon, data, summary
    """
    if not multi_area_results:
        return
    
    st.subheader("📈 Perbandingan Kualitas Udara")
    
    # Siapkan data time series untuk setiap parameter
    # Ambil data terakhir 24 jam dari setiap area
    all_data = []
    for item in multi_area_results:
        city_name = item.get("name", "Unknown")
        df = item.get("data", pd.DataFrame())
        
        if not df.empty and "time" in df.columns:
            # Ambil data terakhir 24 jam dan pastikan time adalah datetime
            df_24h = df.tail(24).copy()
            if not pd.api.types.is_datetime64_any_dtype(df_24h["time"]):
                df_24h["time"] = pd.to_datetime(df_24h["time"])
            df_24h["city"] = city_name
            all_data.append(df_24h)
    
    if not all_data:
        st.info("Tidak ada data time series untuk perbandingan.")
        return
    
    # Gabungkan semua data
    df_combined = pd.concat(all_data, ignore_index=True)
    
    # Fungsi helper untuk membuat line chart per parameter
    def create_line_chart(df, param_col, city_col="city", time_col="time", title=""):
        """Helper untuk membuat line chart dengan multiple cities"""
        if param_col not in df.columns:
            return False
        
        # Buat pivot: time sebagai index, city sebagai columns
        df_chart = df[[time_col, city_col, param_col]].copy()
        df_chart = df_chart.set_index([time_col, city_col])[param_col].unstack(level=city_col)
        
        if not df_chart.empty:
            st.caption(title)
            st.line_chart(df_chart, use_container_width=True)
            return True
        return False
    
    # Helper function untuk membuat line chart
    def make_line_chart(df, param_col, title):
        """Membuat line chart untuk parameter tertentu dengan multiple cities"""
        if param_col not in df.columns:
            return False
        
        try:
            df_chart = df[["time", "city", param_col]].copy()
            # Pivot: time sebagai index, city sebagai columns
            df_pivot = df_chart.pivot(index="time", columns="city", values=param_col)
            
            if not df_pivot.empty:
                st.caption(title)
                st.line_chart(df_pivot, use_container_width=True)
                return True
        except Exception as e:
            st.warning(f"Error membuat chart untuk {param_col}: {e}")
        
        return False
    
    # PM2.5 dan PM10
    if "pm2_5" in df_combined.columns:
        make_line_chart(df_combined, "pm2_5", "📊 PM2.5 (µg/m³)")
    
    if "pm10" in df_combined.columns:
        make_line_chart(df_combined, "pm10", "📊 PM10 (µg/m³)")
    
    # NO2, SO2, Ozone, CO dalam 2 kolom
    col1, col2 = st.columns(2)
    
    with col1:
        if "nitrogen_dioxide" in df_combined.columns:
            make_line_chart(df_combined, "nitrogen_dioxide", "📊 NO₂ (µg/m³)")
        
        if "sulphur_dioxide" in df_combined.columns:
            make_line_chart(df_combined, "sulphur_dioxide", "📊 SO₂ (µg/m³)")
    
    with col2:
        if "ozone" in df_combined.columns:
            make_line_chart(df_combined, "ozone", "📊 Ozone (µg/m³)")
        
        if "carbon_monoxide" in df_combined.columns:
            make_line_chart(df_combined, "carbon_monoxide", "📊 CO (µg/m³)")
