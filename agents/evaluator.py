import os
import google.generativeai as genai
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_community.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter

class AirQualityAgent:
    def __init__(self, api_key, pdf_path):
        self.api_key = api_key
        self.pdf_path = pdf_path
        self.index_path = "faiss_index_store"  # Folder untuk menyimpan memori otak
        self.vector_store = None
        
        # Konfigurasi Gemini
        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel("gemini-2.5-flash")

    def initialize_knowledge_base(self):
        """
        Cek apakah index lokal sudah ada?
        - Jika YA: Load langsung (Cepat, < 2 detik)
        - Jika TIDAK: Baca PDF -> Embed -> Simpan (Lama, butuh CPU)
        """
        # Setup model embedding
        # Model ini akan didownload otomatis jika belum ada di cache
        embedding_model = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")

        # 1. Cek apakah kita sudah pernah memproses PDF ini sebelumnya
        if os.path.exists(self.index_path):
            try:
                print("📂 Memuat Knowledge Base dari disk (Cepat)...")
                # allow_dangerous_deserialization=True diperlukan untuk memuat file lokal pickle
                self.vector_store = FAISS.load_local(
                    self.index_path, 
                    embedding_model, 
                    allow_dangerous_deserialization=True
                )
                return True, "Knowledge base dimuat dari penyimpanan lokal."
            except Exception as e:
                print(f"⚠️ Gagal memuat index lama, membuat ulang: {e}")

        # 2. Jika belum ada atau gagal load, buat dari awal (Proses Berat)
        if not os.path.exists(self.pdf_path):
            return False, "File PDF tidak ditemukan."

        try:
            print("⚙️ Memproses PDF dari awal (Mungkin butuh waktu)...")
            
            # Load PDF
            loader = PyPDFLoader(self.pdf_path)
            pages = loader.load()

            # Split Text
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=1000,
                chunk_overlap=200
            )
            docs = text_splitter.split_documents(pages)

            # Create Embeddings & Store
            self.vector_store = FAISS.from_documents(docs, embedding_model)
            
            # 3. SIMPAN KE DISK agar besok tidak perlu proses ulang
            self.vector_store.save_local(self.index_path)
            print("✅ Knowledge Base berhasil disimpan ke disk.")
            
            return True, "Knowledge base berhasil dibangun dan disimpan."
            
        except Exception as e:
            return False, f"Error membangun knowledge base: {str(e)}"

    def get_relevant_context(self, query, k=4):
        if not self.vector_store:
            return []
        docs = self.vector_store.similarity_search(query, k=k)
        return docs

    def analyze_air_quality(self, user_query, air_quality_json):
        if not self.vector_store:
            return "Maaf, knowledge base belum siap. Silakan restart aplikasi."

        # 1. Cari konteks
        search_query = f"{user_query} PM2.5 PM10 NO2 SO2 Ozone guidelines limits health effects"
        relevant_docs = self.get_relevant_context(search_query)
        context_text = "\n\n".join([doc.page_content for doc in relevant_docs])

        # 2. Prompt untuk Gemini
        prompt = f"""
        Kamu adalah Ahli Analisis Kualitas Udara.
        
        Tugas: Jawab pertanyaan pengguna berdasarkan DATA REAL-TIME dan PANDUAN WHO.
        
        --- DATA KUALITAS UDARA (Real-time) ---
        {air_quality_json}
        
        --- REFERENSI DARI WHO GUIDELINES (Konteks Relevan) ---
        {context_text}
        
        --- PERTANYAAN PENGGUNA ---
        {user_query}
        
        Berikan analisis risiko kesehatan singkat dan rekomendasi konkret dalam Bahasa Indonesia.
        """

        try:
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            return f"Maaf, terjadi kesalahan koneksi ke Gemini: {str(e)}"