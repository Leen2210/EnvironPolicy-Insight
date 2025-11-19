import google.generativeai as genai
from geopy.geocoders import Nominatim
from typing import List, Tuple, Optional
import json

class GeocoderAgent:
    """
    Agent untuk memecah area geografis besar menjadi sub-area (kota) 
    dan mendapatkan koordinatnya.
    """
    def __init__(self, api_key: str):
        self.api_key = api_key
        # Konfigurasi Gemini
        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel("gemini-2.5-flash")
        self.geolocator = Nominatim(user_agent="environpolicy_insight_geocoder")
        
    def extract_location_from_query(self, user_query: str) -> Optional[str]:
        """
        Mendeteksi apakah user menyebutkan nama lokasi spesifik (Provinsi/Negara/Pulau)
        yang membutuhkan analisis multi-area.
        """
        prompt = f"""
        Analisis kalimat user: "{user_query}"
        
        Tugas: Ekstrak nama lokasi geografis target jika user ingin:
        1. Mengetahui kondisi di lokasi tersebut.
        2. Membandingkan lokasi saat ini dengan lokasi tersebut (Contoh: "Bandingkan dengan Surabaya").
        
        Jika user HANYA bertanya medis/umum tanpa menyebut lokasi baru, kembalikan null.
        
        Contoh:
        - "Cek Jakarta" -> {{"location": "Jakarta"}}
        - "Bagaimana jika dibandingkan dengan Surabaya?" -> {{"location": "Surabaya"}}
        - "Apakah polusi berbahaya?" -> {{"location": null}}
        
        Output HANYA JSON:
        """
        # Apakah user meminta data kualitas udara untuk suatu lokasi geografis (Kota, Provinsi, Negara)?
        # Jika YA, sebutkan nama lokasi tersebut dalam format JSON.
        # Jika TIDAK (hanya pertanyaan umum atau medis), kembalikan null.
        
        # Contoh 1: "Bagaimana udara di Jawa Timur?" -> {{"location": "Jawa Timur"}}
        # Contoh 2: "Apakah PM2.5 berbahaya?" -> {{"location": null}}
        # Contoh 3: "Cek polusi Jakarta" -> {{"location": "Jakarta"}}
        try:
            response = self.model.generate_content(prompt)
            text = response.text.strip().replace("```json", "").replace("```", "")
            data = json.loads(text)
            return data.get("location")
        except Exception:
            return None

    def _get_cities_from_area(self, area_name: str) -> List[str]:
        """
        Menggunakan Gemini untuk mendapatkan daftar kota/kabupaten 
        di dalam area yang ditentukan.
        """
        prompt = f"""
        Tugas: Apakah '{area_name}' adalah wilayah luas (Provinsi/Negara/Pulau) atau Kota/Kabupaten spesifik?
        
        - Jika Kota/Kabupaten spesifik (misal: Surabaya, Bandung, Jakarta Selatan), kembalikan list kosong [].
        - Jika Wilayah Luas (misal: Jawa Timur, Indonesia), sebutkan 5-8 kota utamanya.
        
        Keluaran JSON:
        {{
          "cities": ["City A", "City B"] (atau [] jika itu kota spesifik)
        }}
        
        Pastikan output HANYA berisi JSON.
        """
        
        try:
            response = self.model.generate_content(prompt)
            # Membersihkan respons untuk memastikan hanya JSON yang tersisa
            text_content = response.text.strip().replace("```json", "").replace("```", "")
            data = json.loads(text_content)
            return data.get("cities", [])
        except Exception as e:
            print(f"[GeocoderAgent] Error generating content or parsing JSON: {e}")
            return []

    def get_coordinates_for_area(self, area_name: str) -> List[Tuple[str, float, float]]:
        """
        Mengembalikan list tuples (nama, lat, lon).
        Logika Hybrid:
        1. Coba anggap sebagai SINGLE location dulu (Geocoding langsung).
        2. Jika user meminta wilayah luas (detected by Gemini), cari sub-cities.
        """
        results: List[Tuple[str, float, float]] = []

        # 1. Cek apakah ini nama kota spesifik (Single Point)
        try:
            single_loc = self.geolocator.geocode(area_name)
        except:
            single_loc = None

        # 2. Tanya AI apakah ini wilayah luas yang butuh dipecah?
        # (Sederhananya: kita ambil sub-cities. Jika listnya kosong atau cuma 1 nama yang mirip input, berarti single).
        sub_cities = self._get_cities_from_area(area_name)
        
        # KONDISI SINGLE POINT:
        # Jika AI tidak menemukan sub-kota, ATAU sub-kota hanya 1 dan namanya mirip input
        is_single_point = False
        if not sub_cities:
            is_single_point = True
        elif len(sub_cities) == 1 and sub_cities[0].lower() in area_name.lower():
            is_single_point = True

        if is_single_point:
            if single_loc:
                return [(single_loc.address.split(",")[0], single_loc.latitude, single_loc.longitude)]
            return []

        # KONDISI MULTI AREA:
        # Loop sub-cities dan geocode satu per satu
        for name in sub_cities:
            try:
                # Tambahkan konteks area agar akurat (misal: "Bandung, Jawa Barat")
                query_geo = f"{name}, {area_name}" 
                location = self.geolocator.geocode(query_geo)
                if location:
                    # Ambil nama depan saja biar pendek di peta
                    disp_name = name.title()
                    results.append((disp_name, location.latitude, location.longitude))
            except Exception:
                continue
        
        # Fallback: Jika loop gagal semua tapi single_loc ada, kembalikan single loc
        if not results and single_loc:
             return [(single_loc.address.split(",")[0], single_loc.latitude, single_loc.longitude)]

        return results