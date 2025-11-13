from http.server import BaseHTTPRequestHandler
import os, json, base64, hashlib, requests
from Crypto.Cipher import AES
from google.oauth2 import service_account
from googleapiclient.discovery import build

BLOCK_SIZE = 16

# -------- AES Padding -------- #
def pkcs7_pad(data: bytes) -> bytes:
    pad_len = BLOCK_SIZE - len(data) % BLOCK_SIZE
    return data + bytes([pad_len]) * pad_len

# -------- AES Encrypt -------- #
def aes_encrypt(raw_json: str, key: str, iv: str) -> str:
    raw_bytes = raw_json.encode("utf-8")
    key_bytes = key.encode("utf-8")
    iv_bytes = iv.encode("utf-8")

    cipher = AES.new(key_bytes, AES.MODE_CBC, iv_bytes)
    padded = pkcs7_pad(raw_bytes)
    encrypted = cipher.encrypt(padded)

    return base64.b64encode(encrypted).decode("utf-8")

# -------- MD5 Sign -------- #
def make_sign(request_data_b64: str, sign_key: str) -> str:
    m = hashlib.md5()
    m.update((request_data_b64 + sign_key).encode("utf-8"))
    return m.hexdigest()

# -------- Fetch Orders from Trip.com -------- #
def fetch_orders():
    account_id = os.environ["TRIP_ACCOUNT_ID"]
    sign_key = os.environ["TRIP_SIGN_KEY"]
    aes_key = os.environ["TRIP_AES_KEY"]
    aes_iv = os.environ["TRIP_AES_IV"]

    # 샌드박스 주문 요청 파라미터 (필요시 조건 수정 가능)
    biz = {
        "accountId": account_id,
        "pageIndex": 1,
        "pageSize": 20
    }

    raw_json = json.dumps(biz, ensure_ascii=False)

    # AES 암호화
    request_data = aes_encrypt(raw_json, aes_key, aes_iv)

    # MD5 sign 생성
    sign = make_sign(request_data, sign_key)

    payload = {
        "accountId": account_id,
        "requestData": request_data,
        "sign": sign
    }

    # Trip.com 샌드박스 주문 조회 API
    url = "https://ttdopen.ctrip.com/api/order/list"
    resp = requests.post(url, json=payload, timeout=10)
    resp.raise_for_status()

    return resp.json()

# -------- Save to Google Sheets -------- #
def save_to_sheet(orders):
    sheet_id = os.environ["SHEET_ID"]
    service_json = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]

    service_info = json.loads(service_json)

    creds = service_account.Credentials.from_service_account_info(
        service_info,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )

    service = build("sheets", "v4", credentials=creds)
    sheet = service.spreadsheets()

    # 구글시트에 들어갈 데이터 구성
    values = []
    for o in orders:
        values.append([
            o.get("orderId", ""),
            o.get("productName", ""),
            o.get("travelerName", ""),
            o.get("phone", ""),
            o.get("qty", ""),
            o.get("totalAmount", ""),
            o.get("orderTime", "")
        ])

    body = {"values": values}

    # Sheet1!A:G 범위에 append
    sheet.values().append(
        spreadsheetId=sheet_id,
        range="Sheet1!A:G",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body=body
    ).execute()

# -------- HTTP Handler (Vercel Serverless) -------- #
class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            data = fetch_orders()
            orders = data.get("orders", [])

            save_to_sheet(orders)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "ok",
                "orders_fetched": len(orders)
            }).encode())
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(e).encode())
