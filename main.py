from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from PyPDF2 import PdfReader, PdfWriter
import io
import psycopg2
import secrets

# FastAPI uygulaması
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # İzin verilen frontend URL'si
    allow_credentials=True,
    allow_methods=["*"],  # Tüm HTTP metodlarına izin ver
    allow_headers=["*"],  # Tüm başlıklara izin ver
)

# PDF şablon dosyası
template_pdf = "template_certificate.pdf"  # Şablon dosyasının doğru yolunu belirleyin

# Font kayıt işlemleri
pdfmetrics.registerFont(TTFont("Poppins-Regular", "./font/Poppins/Poppins-Regular.ttf"))
pdfmetrics.registerFont(TTFont("Poppins-Medium", "./font/Poppins/Poppins-Medium.ttf"))

# Gelen veriler için bir model tanımı
class CertificateData(BaseModel):
    name: str
    training_name: str
    training_duration: str
    training_date: str

def get_db_connection():
    """PostgreSQL bağlantısını oluşturur ve hata durumunu yönetir."""
    try:
        connection = psycopg2.connect(
            dbname="postgres",
            user="postgres",
            password="admin",
            host="localhost",
            port="5432"
        )
        return connection
    except psycopg2.Error as e:
        print(f"Error connecting to the database: {e}")
        raise

    # PostgreSQL bağlantısını test etme
def test_db_connection():
    try:
        conn = get_db_connection()  # get_db_connection fonksiyonunuzu kullanarak bağlantıyı başlatın
        print("PostgreSQL bağlantısı başarılı!")
        conn.close()
    except Exception as e:
        print(f"Bağlantı hatası: {e}")

test_db_connection()

    

def generate_unique_token():
    """Unique bir sertifika ID'si oluşturur."""
    return secrets.token_hex(16)

def generate_pdf_in_memory(token, data):
    """PDF dosyasını oluştur ve bayt formatında bellekte döndür."""
    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=letter)

    # Font ayarları
    can.setFont("Poppins-Medium", 16)
    can.drawString(209, 455, f"{token}")
    can.setFont("Poppins-Medium", 18)

    # Veri yerleştirme
    can.drawString(209, 407, data["name"])
    can.drawString(209, 350, data["training_name"])
    can.drawString(209, 290, data["training_duration"])
    can.drawString(209, 230, data["training_date"])
    can.save()

    packet.seek(0)
    pdf_data = packet.read()  # PDF'nin tüm içeriğini bayt formatında alıyoruz

    return pdf_data


def save_certificate_to_db(token, data, pdf_bytes):
    """Veritabanına sertifika bilgileri ve PDF içeriğini kaydet."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            query = """
                INSERT INTO certificates (token, name, training_name, training_duration, training_date, pdf_data)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id;
            """
            cursor.execute(query, (
                token,
                data["name"],
                data["training_name"],
                data["training_duration"],
                data["training_date"],
                pdf_bytes,
            ))
            certificate_id = cursor.fetchone()[0]
            conn.commit()
            print(f"Certificate ID: {certificate_id} inserted successfully!")
            return certificate_id
    except Exception as e:
        conn.rollback()
        print(f"Database error: {e}")  # Hata mesajını burada yazdırıyoruz
        raise HTTPException(status_code=500, detail="Database write error.")
    finally:
        conn.close()


@app.post("/generate_certificate")
async def generate_certificate(certificate_data: CertificateData):
    """PDF sertifika oluştur ve kaydet."""
    try:
        # Gelen verileri al
        data = {
            "name": certificate_data.name,
            "training_name": certificate_data.training_name,
            "training_duration": certificate_data.training_duration,
            "training_date": certificate_data.training_date,
        }

        # Unique bir token oluştur
        token = generate_unique_token()

        # PDF'yi bellekte oluştur
        pdf_bytes = generate_pdf_in_memory(token, data)

        # Veritabanına kaydet
        certificate_id = save_certificate_to_db(token, data, pdf_bytes)

        return {
            "message": "Certificate generated successfully!",
            "certificate_id": certificate_id,
            "token": token,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/certificate/{certificate_id}")
async def get_certificate(certificate_id: int):
    """Veritabanından PDF içeriğini getir."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            query = "SELECT name, pdf_data FROM certificates WHERE id = %s;"
            cursor.execute(query, (certificate_id,))
            result = cursor.fetchone()

            if result is None:
                raise HTTPException(status_code=404, detail="Certificate not found.")

            pdf_data = result[1]
            name = result[0]

            # PDF'yi döndür
            return Response(
                pdf_data,
                media_type="application/pdf",
                headers={
                    "Content-Disposition": f"attachment; filename={name}.pdf"
                },
            )
    except Exception as e:
        print(f"Error fetching certificate: {e}")
        raise HTTPException(status_code=500, detail="Database fetch error.")
    finally:
        conn.close()

