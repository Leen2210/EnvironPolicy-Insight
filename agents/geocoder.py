import google.generativeai as genai
from geopy.geocoders import Nominatim
from typing import List, Tuple, Optional, Dict, Any
import json

class GeocoderAgent:
    """
    Agent untuk memecah area geografis menjadi sub-area:
    - Provinsi -> List Kota/Kabupaten
    - Kota/Kabupaten -> List Kecamatan
    Dan mendapatkan koordinatnya.
    """
    def __init__(self, api_key: str):
        self.api_key = api_key
        # Konfigurasi Gemini
        genai.configure(api_key=self.api_key)
        
        # PENTING: Gunakan gemini-2.5-flash yang support JSON Mode native
        self.model = genai.GenerativeModel(
            "gemini-2.5-flash",
            generation_config={"response_mime_type": "application/json"}
        )
        self.geolocator = Nominatim(user_agent="environpolicy_insight_geocoder")
        
    def extract_location_from_query(self, user_query: str, current_date:str) -> Optional[str]:
        """
        Mendeteksi nama lokasi target dari input user.
        """
        prompt = f"""
        konteks waktu saat ini : {current_date}

        Analisis kalimat user berikut:

        "{user_query}"

        Tugas:
        Deteksi maksud user mengenai lokasi geografis. Klasifikasikan ke dalam empat intent:
        1. "single"  → User hanya menyebut 1 lokasi (dengan atau tanpa level administratif).
        2. "subareas" → User meminta daftar sub-area dari sebuah wilayah.
        3. "multi" → User menyebut beberapa area sekaligus.
        4. "none" → User TIDAK meminta area baru, hanya bertanya tentang data yang sudah ada atau pertanyaan umum.

        Gunakan aturan berikut:

        A. SINGLE LOCATION (NO LEVEL)
        - Jika user hanya menyebut nama wilayah tanpa level administratif.
        Contoh: "Jawa Barat", "Indonesia", "Bandung"

        B. SINGLE LOCATION (WITH LEVEL)
        - Jika input mengandung level administratif:
        ["provinsi", "kota", "kabupaten", "kecamatan", "desa", "kelurahan"]

        C. SUB-AREA REQUEST (POLA)
        - Pola eksplisit:
        "<level> di <wilayah>"
        "<level> dalam <wilayah>"
        "<level> pada <wilayah>"
        "<level>-<level> <wilayah>"
        "list <level> <wilayah>"
        "<level> <area> dalam <wilayah>"

        D. MULTI AREA LIST
        - Jika user menyebut lebih dari satu area:
        contoh:
            "Coblong, Sukajadi, Cidadap Bandung"
            "Kecamatan X dan Y pada Kota Z"
            "Cidadap dan Cicendo dalam Bandung"

        E. NONE / CONTEXT QUESTION (PENTING!)
        - Jika user TIDAK menyebut nama area baru, hanya bertanya tentang:
            • Data yang sudah ditampilkan: "apakah ini berbahaya?", "bagaimana kualitas udaranya?", "apakah aman?"
            • Pertanyaan umum tanpa area: "apa itu PM2.5?", "bagaimana cara membaca data ini?"
            • Perbandingan dengan area lain: "bandingkan dengan Jakarta", "lebih buruk dari mana?"
            • Pertanyaan analisis: "apa penyebabnya?", "kapan waktu terbaik?"
        - Jika user hanya bertanya tentang konteks tanpa menyebut area baru → intent = "none"

        Output JSON Schema:{{
        "intent": "single" | "subareas" | "multi" | "none",
        "level": "province" | "city" | "regency" | "district" | "village" | null,
        "areas": ["Area1", "Area2", ...] | [],
        "parent_area": "Nama wilayah induk atau null", 
        "date_range": {{
            "start": "YYYY-MM-DD",
            "end": "YYYY-MM-DD}}}}

        CATATAN:
        - Jika intent = "none", maka areas = [] dan parent_area = null
        - "areas" selalu berupa list:
            • single → 1 item
            • subareas → daftar sub-area yang diminta
            • multi → daftar area yang disebut user
            • none → [] (kosong)
        - "parent_area" hanya digunakan untuk sub-area request.
        
        PENTING:
        - Jika user TIDAK menyebut nama area baru, PASTIKAN intent = "none"
        - Jawab HANYA dalam format JSON yang valid.
        - Jangan menambahkan teks, penjelasan, komentar, catatan, atau markdown.
        - Output HARUS dimulai dengan karakter pertama '{' dan berakhir dengan '}'.
        """

        try:
            response = self.model.generate_content(prompt)
            data = json.loads(response.text)
            return data
        except Exception as e:
            print(f"[Geocoder] Error extract location: {e}")
            return None

    def _get_regions_from_area(self, user_query: str, area_name: str, intent_data: Dict[str, Any]) -> List[str]:
        """
        Meminta AI memecah wilayah menjadi sub-area berdasarkan level yang diminta.
        Mengembalikan daftar NAMA SUB-AREA yang sebenarnya (bukan kata level).
        """
        level = intent_data.get("level")
        parent_area = intent_data.get("parent_area", area_name)
        
        # Mapping level ke bahasa Indonesia
        level_map = {
            "province": "provinsi",
            "city": "kota",
            "regency": "kabupaten", 
            "district": "kecamatan",
            "village": "desa"
        }
        level_id = level_map.get(level, level) if level else None
        
        prompt = f"""
        Tugas: Berikan daftar NAMA SUB-AREA yang sebenarnya dari wilayah '{parent_area}'.
        
        Query user: "{user_query}"
        Level yang diminta: {level_id if level_id else 'tidak ditentukan'}
        Wilayah induk: {parent_area}
        
        INSTRUKSI:
        1. Jika level yang diminta adalah "kecamatan" atau "district":
           → Berikan daftar NAMA KECAMATAN yang ada di {parent_area}.
           → Contoh untuk Surabaya: ["Gubeng", "Sukolilo", "Wonokromo", "Tegalsari", "Simokerto", ...]
        
        2. Jika level yang diminta adalah "kota" atau "city":
           → Berikan daftar NAMA KOTA yang ada di {parent_area}.
           → Contoh untuk Jawa Timur: ["Surabaya", "Malang", "Sidoarjo", "Gresik", ...]
        
        3. Jika level yang diminta adalah "kabupaten" atau "regency":
           → Berikan daftar NAMA KABUPATEN yang ada di {parent_area}.
        
        4. Jika level yang diminta adalah "provinsi" atau "province":
           → Berikan daftar NAMA PROVINSI yang ada di {parent_area} (biasanya untuk Indonesia).
        
        PENTING:
        - Kembalikan NAMA-NAMA SUB-AREA yang SEBENARNYA, BUKAN kata "kecamatan", "kota", dll.
        - Gunakan pengetahuan geografis Indonesia yang akurat.
        - MAKSIMAL berikan 5 sub-area yang paling representatif/penting.
        - Pilih sub-area yang paling dikenal atau paling relevan.
        
        Output JSON:
        {{ "sub_areas": ["Nama Sub-Area 1", "Nama Sub-Area 2", "Nama Sub-Area 3", ...] }}
        
        CATATAN:
        - Jawab HANYA dalam format JSON yang valid.
        - Jangan menambahkan teks, penjelasan, komentar, catatan, atau markdown.
        - Output HARUS dimulai dengan karakter pertama '{{' dan berakhir dengan '}}'.
        """

        try:
            response = self.model.generate_content(prompt)
            data = json.loads(response.text)
            sub_areas = data.get("sub_areas", [])
            
            # Filter: Hapus jika hanya berisi kata level (bukan nama sebenarnya)
            filtered = []
            level_words = ["kecamatan", "kota", "kabupaten", "provinsi", "desa", "kelurahan", "district", "city", "regency", "province"]
            for area in sub_areas:
                area_lower = area.lower().strip()
                # Skip jika hanya kata level tanpa nama area
                if area_lower not in level_words and len(area_lower) > 2:
                    filtered.append(area)
            
            final_list = filtered if filtered else sub_areas
            # Batasi maksimal 5 sub-area
            return final_list[:5]
        except Exception as e:
            print(f"[Geocoder] Error AI decomposition: {e}")
            return []
    def get_coordinates_for_area(
    self,
    user_query: str,
    area_name: str,
    intent_data: Dict[str, Any]
) -> List[Tuple[str, float, float]]:
        """
        Mengembalikan list tuples (nama, lat, lon) berdasarkan intent:
        1. Single: Hanya 1 koordinat.
        2. Multi/Subareas: Banyak koordinat.
        area_name adalah nama wilayah induk yang akan dipecah (misal: "Jawa Timur").
        """

        results: List[Tuple[str, float, float]] = []
        is_single_point = False
        sub_regions: List[str] = []

        intent_type = intent_data.get("intent")

        # ---------------------------
        # 1. Tentukan mode
        # ---------------------------
        if intent_type == "single":
            is_single_point = True

        elif intent_type == "multi":
            sub_regions = intent_data.get("areas", [])

        elif intent_type == "subareas":
            sub_regions = self._get_regions_from_area(user_query, area_name, intent_data)

        # Kalau tidak dapat sub-area, fallback ke single point (kecuali explicit multi)
        if not sub_regions and intent_type != "multi":
            is_single_point = True

        # ---------------------------
        # 2. Coba geocode area induk untuk single atau fallback
        # ---------------------------
        try:
            single_loc = self.geolocator.geocode(area_name)
        except:
            single_loc = None

        # ---------------------------
        # 3. SINGLE POINT
        # ---------------------------
        if is_single_point:
            if single_loc:
                display_name = single_loc.address.split(",")[0]
                return [(display_name, single_loc.latitude, single_loc.longitude)]
            return []

        # ---------------------------
        # 4. MULTI / SUB-AREAS
        # ---------------------------
        print(f"[Geocoder] Breaking down '{area_name}' into: {sub_regions}")

        for name in sub_regions:
            try:
                query_geo = f"{name}, {area_name}"
                location = self.geolocator.geocode(query_geo)

                if location:
                    disp_name = name.title()
                    results.append((disp_name, location.latitude, location.longitude))
                    continue

                # fallback: geocode nama sub-area saja
                location = self.geolocator.geocode(name)
                if location:
                    disp_name = name.title()
                    results.append((disp_name, location.latitude, location.longitude))

            except Exception as e:
                print(f"Error geocoding {name}: {e}")
                continue

        # ---------------------------
        # 5. Fallback terakhir ke single_loc bila tidak ada hasil
        # ---------------------------
        if not results and single_loc:
            print(f"[Geocoder] Fallback to single point for {area_name}.")
            return [(single_loc.address.split(",")[0], single_loc.latitude, single_loc.longitude)]

        return results
