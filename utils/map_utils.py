import folium

def make_map(center_coords, zoom=9):
    return folium.Map(location=center_coords, zoom_start=zoom)

def add_markers(m, coords, result):
    if not result or "data" not in result:
        folium.Marker(
            location=coords,
            tooltip="Tidak ada data ditemukan",
            icon=folium.Icon(color="red", icon="exclamation-sign")
        ).add_to(m)
        return m
    
    city = result["location_name"]
    source = result["source"]
    is_nearest = "Nearest Station" in source
    
    if is_nearest:
        folium.Marker(
            location=coords,
            tooltip="Lokasi Pilihan Anda",
            icon=folium.Icon(color="orange", icon="cloud")
        ).add_to(m)
        folium.Marker(
            location=[result["latitude"], result["longitude"]],
            tooltip=f"Sumber Data: {city}",
            icon=folium.Icon(color="blue", icon="info-sign")
        ).add_to(m)
    else:
        folium.Marker(
            location=coords,
            tooltip=f"Lokasi: {city}",
            icon=folium.Icon(color="green", icon="cloud")
        ).add_to(m)
    return m
