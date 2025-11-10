import streamlit as st

def display_air_quality_charts(df):
    chart_cols = [col for col in ["pm2_5", "pm10"] if col in df.columns]
    if not chart_cols:
        st.info("Tidak ada kolom PM2.5 atau PM10 untuk divisualisasikan.")
        return
    st.subheader("📈 Tren PM2.5 dan PM10")
    st.line_chart(df.set_index("time")[chart_cols])
