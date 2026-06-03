import os
import uuid
import sqlite3
import json
import time
import threading
import cv2
import numpy as np
import yt_dlp
import imageio_ffmpeg
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from fastapi import FastAPI, BackgroundTasks, HTTPException, Request, Depends
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel, field_validator
from jose import JWTError, jwt as jose_jwt
import hashlib
import secrets

DATABASE_URL = os.getenv("DATABASE_URL", "tibe.db")
SECRET_KEY = os.getenv("SECRET_KEY", "change-this-to-a-very-long-random-secret-key-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))
PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY", "")
PAYSTACK_PUBLIC_KEY = os.getenv("PAYSTACK_PUBLIC_KEY", "")
AD_WATCH_DURATION_SECONDS = int(os.getenv("AD_WATCH_DURATION_SECONDS", "30"))
AD_WATCH_COOLDOWN_MINUTES = int(os.getenv("AD_WATCH_COOLDOWN_MINUTES", "60"))
PRICING_PLANS_JSON = os.getenv("PRICING_PLANS", json.dumps([
    {"name": "Starter", "units": 10, "price_cents": 999, "popular": False},
    {"name": "Pro", "units": 30, "price_cents": 2499, "popular": True},
    {"name": "Ultra", "units": 100, "price_cents": 6999, "popular": False},
]))
MAX_FRAME_WORKERS = int(os.getenv("MAX_FRAME_WORKERS", str(os.cpu_count() or 4)))

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
APPLE_CLIENT_ID = os.getenv("APPLE_CLIENT_ID", "")
APPLE_TEAM_ID = os.getenv("APPLE_TEAM_ID", "")
APPLE_KEY_ID = os.getenv("APPLE_KEY_ID", "")
APPLE_PRIVATE_KEY_PATH = os.getenv("APPLE_PRIVATE_KEY_PATH", "")

CURRENCY_RATES = {
    "USD": {"symbol": "$", "rate": 1.0, "code": "USD"},
    "EUR": {"symbol": "\u20ac", "rate": 0.92, "code": "EUR"},
    "GBP": {"symbol": "\u00a3", "rate": 0.79, "code": "GBP"},
    "JPY": {"symbol": "\u00a5", "rate": 149.5, "code": "JPY"},
    "NGN": {"symbol": "\u20a6", "rate": 1550.0, "code": "NGN"},
    "INR": {"symbol": "\u20b9", "rate": 83.5, "code": "INR"},
    "CAD": {"symbol": "C$", "rate": 1.37, "code": "CAD"},
    "AUD": {"symbol": "A$", "rate": 1.54, "code": "AUD"},
    "BRL": {"symbol": "R$", "rate": 5.05, "code": "BRL"},
    "KES": {"symbol": "KSh", "rate": 145.0, "code": "KES"},
    "ZAR": {"symbol": "R", "rate": 18.5, "code": "ZAR"},
    "GHS": {"symbol": "GH\u20b5", "rate": 12.3, "code": "GHS"},
    "MXN": {"symbol": "Mex$", "rate": 17.2, "code": "MXN"},
    "SGD": {"symbol": "S$", "rate": 1.35, "code": "SGD"},
    "CHF": {"symbol": "Fr", "rate": 0.88, "code": "CHF"},
}

LOCALE_CURRENCY = {
    "en-US": "USD", "en-GB": "GBP", "en-IE": "EUR",
    "fr-FR": "EUR", "de-DE": "EUR", "it-IT": "EUR", "es-ES": "EUR",
    "ja-JP": "JPY", "en-NG": "NGN", "ha-NG": "NGN", "yo-NG": "NGN",
    "ig-NG": "NGN", "en-IN": "INR", "hi-IN": "INR",
    "en-CA": "CAD", "fr-CA": "CAD", "en-AU": "AUD", "pt-BR": "BRL",
    "en-KE": "KES", "sw-KE": "KES", "en-ZA": "ZAR", "af-ZA": "ZAR",
    "zu-ZA": "ZAR", "en-GH": "GHS", "es-MX": "MXN", "en-SG": "SGD",
    "de-CH": "CHF", "fr-CH": "CHF",
}

HASH_ALGO = "sha256"
HASH_SALT_LENGTH = 32
HASH_ITERATIONS = 260000

def get_password_hash(password: str) -> str:
    salt = secrets.token_hex(HASH_SALT_LENGTH)
    dk = hashlib.pbkdf2_hmac(HASH_ALGO, password.encode(), salt.encode(), HASH_ITERATIONS)
    return f"{HASH_ITERATIONS}${HASH_ALGO}${salt}${dk.hex()}"

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        iterations, algo, salt, expected = hashed_password.split("$")
        dk = hashlib.pbkdf2_hmac(algo, plain_password.encode(), salt.encode(), int(iterations))
        return dk.hex() == expected
    except Exception:
        return False

def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jose_jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def create_refresh_token(data: dict):
    return create_access_token(data, expires_delta=timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS))

def decode_token(token: str):
    try:
        return jose_jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None

async def get_current_user(request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    token = auth_header.split(" ")[1]
    payload = decode_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

db_lock = threading.Lock()
tasks_db_lock = threading.Lock()
tasks_db = {}

def get_db():
    conn = sqlite3.connect(DATABASE_URL, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn

db = get_db()

def init_db():
    with db_lock:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL, units_balance INTEGER NOT NULL DEFAULT 0,
                is_premium INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS transactions (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
                amount_cents INTEGER NOT NULL, currency TEXT NOT NULL DEFAULT 'usd',
                provider TEXT NOT NULL, provider_txn_id TEXT,
                units_added INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS downloads (
                id TEXT PRIMARY KEY, user_id TEXT, task_id TEXT UNIQUE,
                url TEXT NOT NULL, quality TEXT NOT NULL DEFAULT '1080p',
                enhanced INTEGER NOT NULL DEFAULT 0, units_spent INTEGER NOT NULL DEFAULT 0,
                ad_watch_id TEXT, file_size_bytes INTEGER DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS ad_watches (
                id TEXT PRIMARY KEY, user_id TEXT, ip_address TEXT,
                completed_at TEXT NOT NULL DEFAULT (datetime('now')),
                expires_at TEXT NOT NULL, FOREIGN KEY (user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS rate_limits (
                ip TEXT NOT NULL, endpoint TEXT NOT NULL, timestamp REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_rate_limits_ip ON rate_limits(ip, timestamp);
            CREATE INDEX IF NOT EXISTS idx_ad_watches_ip ON ad_watches(ip_address, completed_at);
            CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions(user_id);
            CREATE INDEX IF NOT EXISTS idx_downloads_user ON downloads(user_id);
        """)
        db.commit()

init_db()

def get_user_by_id(user_id: str):
    with db_lock:
        row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

def get_user_by_email(email: str):
    with db_lock:
        row = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        return dict(row) if row else None

def create_user(email: str, password_hash: str):
    user_id = str(uuid.uuid4())
    with db_lock:
        db.execute("INSERT INTO users (id, email, password_hash) VALUES (?, ?, ?)", (user_id, email, password_hash))
        db.commit()
    return get_user_by_id(user_id)

def add_units(user_id: str, units: int):
    with db_lock:
        db.execute("UPDATE users SET units_balance = units_balance + ? WHERE id = ?", (units, user_id))
        db.commit()

def deduct_unit(user_id: str) -> int:
    with db_lock:
        row = db.execute("SELECT units_balance FROM users WHERE id = ?", (user_id,)).fetchone()
        if row and row["units_balance"] > 0:
            db.execute("UPDATE users SET units_balance = units_balance - 1 WHERE id = ?", (user_id,))
            db.commit()
            return row["units_balance"] - 1
        return -1

def create_transaction(user_id: str, amount_cents: int, provider: str, provider_txn_id: str, units_added: int, status: str = "completed"):
    txn_id = str(uuid.uuid4())
    with db_lock:
        db.execute("INSERT INTO transactions (id, user_id, amount_cents, provider, provider_txn_id, units_added, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (txn_id, user_id, amount_cents, provider, provider_txn_id, units_added, status))
        db.commit()
    return txn_id

def record_download(user_id, task_id, url, quality, enhanced, units_spent=0, ad_watch_id=None, file_size=0):
    dl_id = str(uuid.uuid4())
    with db_lock:
        db.execute("INSERT INTO downloads (id, user_id, task_id, url, quality, enhanced, units_spent, ad_watch_id, file_size_bytes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (dl_id, user_id, task_id, url, quality, 1 if enhanced else 0, units_spent, ad_watch_id, file_size))
        db.commit()

def record_ad_watch(user_id=None, ip_address=None):
    watch_id = str(uuid.uuid4())
    expires_at = (datetime.utcnow() + timedelta(minutes=AD_WATCH_COOLDOWN_MINUTES)).isoformat()
    with db_lock:
        db.execute("INSERT INTO ad_watches (id, user_id, ip_address, expires_at) VALUES (?, ?, ?, ?)",
            (watch_id, user_id, ip_address, expires_at))
        db.commit()
    return watch_id

def is_ad_available(ip_address: str, user_id=None):
    with db_lock:
        if user_id:
            row = db.execute("SELECT expires_at FROM ad_watches WHERE (user_id = ? OR ip_address = ?) AND expires_at > datetime('now') ORDER BY completed_at DESC LIMIT 1",
                (user_id, ip_address)).fetchone()
        else:
            row = db.execute("SELECT expires_at FROM ad_watches WHERE ip_address = ? AND expires_at > datetime('now') ORDER BY completed_at DESC LIMIT 1",
                (ip_address,)).fetchone()
    return row is None

RATE_LIMIT_WINDOW = 60
RATE_LIMIT_MAX_REQUESTS = 10

def check_rate_limit(ip: str, endpoint: str) -> bool:
    now = time.time()
    cutoff = now - RATE_LIMIT_WINDOW
    with db_lock:
        db.execute("DELETE FROM rate_limits WHERE timestamp < ?", (cutoff,))
        count = db.execute("SELECT COUNT(*) as cnt FROM rate_limits WHERE ip = ? AND endpoint = ? AND timestamp > ?",
            (ip, endpoint, cutoff)).fetchone()["cnt"]
        if count >= RATE_LIMIT_MAX_REQUESTS:
            return False
        db.execute("INSERT INTO rate_limits (ip, endpoint, timestamp) VALUES (?, ?, ?)", (ip, endpoint, now))
        db.commit()
    return True

def get_pricing_plans():
    return json.loads(PRICING_PLANS_JSON)

def validate_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if not parsed.scheme or parsed.scheme not in ["http", "https"]:
            return False
        if not parsed.netloc:
            return False
        blocked = ["localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]", "10.", "172.16.", "172.17.", "172.18.", "172.19.", "172.20.", "172.21.", "172.22.", "172.23.", "172.24.", "172.25.", "172.26.", "172.27.", "172.28.", "172.29.", "172.30.", "172.31.", "192.168."]
        for b in blocked:
            if parsed.netloc.startswith(b):
                return False
        return True
    except Exception:
        return False

class RegisterRequest(BaseModel):
    email: str
    password: str
    @field_validator("email")
    @classmethod
    def valid_email(cls, v):
        if "@" not in v or "." not in v.split("@")[-1]:
            raise ValueError("Invalid email address")
        return v.lower().strip()
    @field_validator("password")
    @classmethod
    def strong_password(cls, v):
        if len(v) < 6:
            raise ValueError("Password must be at least 6 characters")
        return v

class LoginRequest(BaseModel):
    email: str
    password: str

class VideoRequest(BaseModel):
    url: str
    quality: str = "1080p"
    ultra_enhance: bool = False

class PaystackInitializeRequest(BaseModel):
    plan_units: int
    amount_cents: int

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield

app = FastAPI(title="TiBe Web API", description="Backend for TiBe Video Processing SaaS", lifespan=lifespan, version="2.0.0")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.add_middleware(GZipMiddleware, minimum_size=1000)

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

# --- Auth Endpoints ---
@app.post("/api/auth/register")
async def register(req: RegisterRequest):
    existing = get_user_by_email(req.email)
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")
    password_hash = get_password_hash(req.password)
    user = create_user(req.email, password_hash)
    access_token = create_access_token({"sub": user["id"]})
    refresh_token = create_refresh_token({"sub": user["id"]})
    return {"access_token": access_token, "refresh_token": refresh_token, "token_type": "bearer",
        "user": {"id": user["id"], "email": user["email"], "units_balance": user["units_balance"]}}

@app.post("/api/auth/login")
async def login(req: LoginRequest):
    user = get_user_by_email(req.email)
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    access_token = create_access_token({"sub": user["id"]})
    refresh_token = create_refresh_token({"sub": user["id"]})
    return {"access_token": access_token, "refresh_token": refresh_token, "token_type": "bearer",
        "user": {"id": user["id"], "email": user["email"], "units_balance": user["units_balance"]}}

@app.post("/api/auth/refresh")
async def refresh_token(request: Request):
    body = await request.json()
    token = body.get("refresh_token")
    if not token:
        raise HTTPException(status_code=400, detail="Missing refresh_token")
    payload = decode_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    user_id = payload.get("sub")
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    access_token = create_access_token({"sub": user["id"]})
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/api/user/me")
async def get_me(user: dict = Depends(get_current_user)):
    fresh = get_user_by_id(user["id"])
    return {"id": fresh["id"], "email": fresh["email"], "units_balance": fresh["units_balance"],
        "is_premium": bool(fresh["is_premium"]), "created_at": fresh["created_at"]}

# --- OAuth ---
OAUTH_SUCCESS_HTML = """<!DOCTYPE html><html><body><script>
window.opener.postMessage({type:"oauth_result",payload:%s},"*");
window.close();
</script></body></html>"""

@app.get("/api/auth/oauth/config")
async def oauth_config():
    return {"google_configured": bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET),
        "apple_configured": bool(APPLE_CLIENT_ID and APPLE_TEAM_ID),
        "google_client_id": GOOGLE_CLIENT_ID or ""}

@app.get("/api/auth/google/login")
async def google_login(request: Request):
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=501, detail="Google OAuth not configured")
    redirect_uri = str(request.base_url).rstrip("/") + "/api/auth/google/callback"
    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?client_id={GOOGLE_CLIENT_ID}&redirect_uri={redirect_uri}&response_type=code&scope=openid+email+profile&access_type=offline"
    return {"auth_url": auth_url}

@app.get("/api/auth/google/callback")
async def google_callback(code: str = "", request: Request = None):
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")
    import httpx
    redirect_uri = str(request.base_url).rstrip("/") + "/api/auth/google/callback"
    async with httpx.AsyncClient() as client:
        token_resp = await client.post("https://oauth2.googleapis.com/token", data={
            "code": code, "client_id": GOOGLE_CLIENT_ID, "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": redirect_uri, "grant_type": "authorization_code"})
        if token_resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to exchange auth code")
        token_json = token_resp.json()
        userinfo_resp = await client.get("https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {token_json['access_token']}"})
        if userinfo_resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to get user info")
        userinfo = userinfo_resp.json()
    email = userinfo.get("email", "").lower().strip()
    if not email:
        raise HTTPException(status_code=400, detail="No email from Google")
    user = get_user_by_email(email)
    if not user:
        password_hash = get_password_hash(str(uuid.uuid4()) + email)
        user = create_user(email, password_hash)
    access_token = create_access_token({"sub": user["id"]})
    refresh_token = create_refresh_token({"sub": user["id"]})
    payload = json.dumps({"access_token": access_token, "refresh_token": refresh_token, "token_type": "bearer",
        "user": {"id": user["id"], "email": user["email"], "units_balance": user["units_balance"]}})
    return HTMLResponse(content=OAUTH_SUCCESS_HTML % payload)

@app.get("/api/auth/apple/login")
async def apple_login(request: Request):
    if not APPLE_CLIENT_ID:
        raise HTTPException(status_code=501, detail="Apple OAuth not configured")
    redirect_uri = str(request.base_url).rstrip("/") + "/api/auth/apple/callback"
    auth_url = f"https://appleid.apple.com/auth/authorize?client_id={APPLE_CLIENT_ID}&redirect_uri={redirect_uri}&response_type=code+id_token&scope=name+email&response_mode=form_post"
    return {"auth_url": auth_url}

@app.post("/api/auth/apple/callback")
async def apple_callback(request: Request):
    form = await request.form()
    id_token = form.get("id_token")
    if not id_token:
        raise HTTPException(status_code=400, detail="Missing id_token")
    try:
        payload = jose_jwt.decode(id_token, "", options={"verify_signature": False})
        email = payload.get("email", "").lower().strip()
        if not email:
            raise HTTPException(status_code=400, detail="No email from Apple")
    except JWTError:
        raise HTTPException(status_code=400, detail="Invalid id_token")
    user = get_user_by_email(email)
    if not user:
        password_hash = get_password_hash(str(uuid.uuid4()) + email)
        user = create_user(email, password_hash)
    access_token = create_access_token({"sub": user["id"]})
    refresh_token = create_refresh_token({"sub": user["id"]})
    payload = json.dumps({"access_token": access_token, "refresh_token": refresh_token, "token_type": "bearer",
        "user": {"id": user["id"], "email": user["email"], "units_balance": user["units_balance"]}})
    return HTMLResponse(content=OAUTH_SUCCESS_HTML % payload)

# --- Pricing & Currency ---
@app.get("/api/pricing")
async def get_pricing():
    return {"plans": get_pricing_plans(), "currencies": CURRENCY_RATES, "locale_currency_map": LOCALE_CURRENCY}

@app.get("/api/currencies")
async def get_currencies():
    return {"currencies": CURRENCY_RATES, "locale_currency_map": LOCALE_CURRENCY}

# --- Paystack ---
@app.post("/api/payment/paystack/initialize")
async def paystack_initialize(req: PaystackInitializeRequest, request: Request, user: dict = Depends(get_current_user)):
    if not PAYSTACK_SECRET_KEY:
        raise HTTPException(status_code=501, detail="Paystack not configured. Set PAYSTACK_SECRET_KEY.")
    import httpx
    base_url = str(request.base_url).rstrip("/")
    callback_url = base_url + "/payment/verify?trxref={reference}"
    async with httpx.AsyncClient() as client:
        resp = await client.post("https://api.paystack.co/transaction/initialize", json={
            "email": user["email"], "amount": str(req.amount_cents), "currency": "USD",
            "callback_url": callback_url, "metadata": {"user_id": user["id"], "units": req.plan_units}},
            headers={"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}", "Content-Type": "application/json"})
        data = resp.json()
        if not data.get("status"):
            raise HTTPException(status_code=400, detail=f"Paystack error: {data.get('message', 'Unknown')}")
        return {"authorization_url": data["data"]["authorization_url"], "reference": data["data"]["reference"]}

@app.get("/api/payment/paystack/verify")
async def paystack_verify(reference: str = ""):
    if not reference:
        raise HTTPException(status_code=400, detail="Missing transaction reference")
    if not PAYSTACK_SECRET_KEY:
        raise HTTPException(status_code=501, detail="Paystack not configured")
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"https://api.paystack.co/transaction/verify/{reference}",
            headers={"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"})
        data = resp.json()
        if not data.get("status"):
            raise HTTPException(status_code=400, detail=f"Verification failed: {data.get('message', 'Unknown')}")
        tx_data = data["data"]
        if tx_data["status"] == "success":
            metadata = tx_data.get("metadata", {})
            user_id = metadata.get("user_id")
            units = int(metadata.get("units", 0))
            amount_cents = tx_data.get("amount", 0)
            if user_id and units > 0:
                add_units(user_id, units)
                create_transaction(user_id, amount_cents, "paystack", reference, units)
            return {"status": "success", "units_added": units, "amount": amount_cents}
        raise HTTPException(status_code=400, detail=f"Payment not successful: {tx_data.get('gateway_response', 'Unknown')}")

@app.post("/api/payment/paystack/webhook")
async def paystack_webhook(request: Request):
    if not PAYSTACK_SECRET_KEY:
        raise HTTPException(status_code=501, detail="Paystack not configured")
    import hmac
    body = await request.body()
    sig = request.headers.get("x-paystack-signature", "")
    expected_sig = hmac.new(PAYSTACK_SECRET_KEY.encode(), body, hashlib.sha512).hexdigest()
    if sig != expected_sig:
        raise HTTPException(status_code=400, detail="Invalid webhook signature")
    event = json.loads(body)
    if event.get("event") == "charge.success":
        tx_data = event["data"]
        metadata = tx_data.get("metadata", {})
        user_id = metadata.get("user_id")
        units = int(metadata.get("units", 0))
        if user_id and units > 0:
            add_units(user_id, units)
            create_transaction(user_id, tx_data.get("amount", 0), "paystack", tx_data.get("reference", ""), units)
    return {"status": "ok"}

# --- Ad System ---
@app.post("/api/ads/check")
async def check_ad_availability(request: Request, user: dict = Depends(get_current_user)):
    return {"ad_available": is_ad_available(request.client.host, user["id"]), "duration_seconds": AD_WATCH_DURATION_SECONDS}

@app.post("/api/ads/complete")
async def complete_ad_watch(request: Request, user: dict = Depends(get_current_user)):
    if not is_ad_available(request.client.host, user["id"]):
        raise HTTPException(status_code=429, detail="Ad cooldown active. Please wait.")
    watch_id = record_ad_watch(user["id"], request.client.host)
    return {"ad_watch_id": watch_id, "message": "Ad watch recorded. You can now process a video."}

# --- Video Processing ---
def ultra_enhance_parallel(video_path, output_path, task_id, num_workers=None):
    if num_workers is None:
        num_workers = MAX_FRAME_WORKERS
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise Exception("Failed to open raw video file")
    w, h = int(cap.get(3)), int(cap.get(4))
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames <= 0:
        total_frames = 1
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_path, fourcc, fps, (w, h))

    def process_frame(frame_data):
        idx, frame = frame_data
        frame = cv2.fastNlMeansDenoisingColored(frame, None, 10, 10, 7, 21)
        frame = cv2.detailEnhance(frame, sigma_s=10, sigma_r=0.15)
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        l = cv2.equalizeHist(l)
        frame = cv2.merge((l, a, b))
        frame = cv2.cvtColor(frame, cv2.COLOR_LAB2BGR)
        return (idx, frame)

    frames = []
    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frames.append((frame_idx, frame))
        frame_idx += 1
    cap.release()
    total = len(frames)
    processed = [None] * total
    batch_size = max(1, total // (num_workers * 4))
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        for i in range(0, total, batch_size):
            batch = frames[i:i + batch_size]
            futures = {executor.submit(process_frame, f): f[0] for f in batch}
            for future in as_completed(futures):
                idx, result = future.result()
                processed[idx] = result
            progress = 50 + int(45 * min(i + batch_size, total) / total)
            with tasks_db_lock:
                if task_id in tasks_db:
                    tasks_db[task_id]["progress"] = progress
    for frame_data in processed:
        out.write(frame_data)
    out.release()

def process_video_task(task_id: str, request: VideoRequest, user=None):
    with tasks_db_lock:
        tasks_db[task_id] = {"status": "processing", "progress": 0, "file": None}
    downloads_dir = "downloads_server"
    os.makedirs(downloads_dir, exist_ok=True)
    raw_video_path = os.path.join(downloads_dir, f"raw_{task_id}.mp4")
    final_video_path = os.path.join(downloads_dir, f"final_{task_id}.mp4")
    try:
        with tasks_db_lock:
            tasks_db[task_id]["status"] = "downloading"
        height_map = {"720p": 720, "1080p": 1080, "2K": 1440, "4K": 2160}
        target_height = height_map.get(request.quality, 1080)
        ydl_opts = {
            'format': f'bestvideo[height<={target_height}][ext=mp4]+bestaudio[ext=m4a]/best[height<={target_height}][ext=mp4]/best',
            'outtmpl': raw_video_path, 'merge_output_format': 'mp4',
            'noplaylist': True, 'overwrites': True,
            'ffmpeg_location': imageio_ffmpeg.get_ffmpeg_exe()}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([request.url])
        with tasks_db_lock:
            tasks_db[task_id]["progress"] = 50
        if request.ultra_enhance:
            with tasks_db_lock:
                tasks_db[task_id]["status"] = "enhancing"
            silent_video_path = os.path.join(downloads_dir, f"silent_{task_id}.mp4")
            ultra_enhance_parallel(raw_video_path, silent_video_path, task_id)
            with tasks_db_lock:
                tasks_db[task_id]["status"] = "merging audio"
                tasks_db[task_id]["progress"] = 96
            ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
            cmd = [ffmpeg_path, "-y", "-i", silent_video_path, "-i", raw_video_path,
                "-map", "0:v", "-map", "1:a?", "-c:v", "copy", "-c:a", "aac", final_video_path]
            startupinfo = subprocess.STARTUPINFO() if os.name == 'nt' else None
            if startupinfo:
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=startupinfo)
            for p in [raw_video_path, silent_video_path]:
                if os.path.exists(p):
                    os.remove(p)
        else:
            if os.path.exists(raw_video_path):
                os.rename(raw_video_path, final_video_path)
        file_size = os.path.getsize(final_video_path) if os.path.exists(final_video_path) else 0
        with tasks_db_lock:
            tasks_db[task_id]["status"] = "completed"
            tasks_db[task_id]["progress"] = 100
            tasks_db[task_id]["file"] = final_video_path
        if user:
            record_download(user["id"], task_id, request.url, request.quality, request.ultra_enhance, file_size=file_size)
    except Exception as e:
        with tasks_db_lock:
            tasks_db[task_id]["status"] = "failed"
            tasks_db[task_id]["error"] = str(e)

@app.post("/api/process")
async def process_video(video_request: VideoRequest, background_tasks: BackgroundTasks, request: Request, user: dict = Depends(get_current_user)):
    if not check_rate_limit(request.client.host, "/api/process"):
        raise HTTPException(status_code=429, detail="Too many requests. Please slow down.")
    if not validate_url(video_request.url):
        raise HTTPException(status_code=400, detail="Invalid video URL.")
    ad_watch_id = request.headers.get("X-Ad-Watch-Id")
    remaining = user["units_balance"]
    if remaining > 0:
        remaining = deduct_unit(user["id"])
        if remaining < 0:
            raise HTTPException(status_code=402, detail="No units remaining.")
        units_spent = 1
    elif ad_watch_id:
        with db_lock:
            watch = db.execute("SELECT id FROM ad_watches WHERE id = ? AND expires_at > datetime('now')", (ad_watch_id,)).fetchone()
        if not watch:
            raise HTTPException(status_code=400, detail="Invalid or expired ad watch.")
        units_spent = 0
    else:
        raise HTTPException(status_code=402, detail="No units remaining. Purchase units or watch an ad to continue.")
    task_id = str(uuid.uuid4())
    background_tasks.add_task(process_video_task, task_id, video_request, user)
    return {"task_id": task_id, "message": "Video processing started.", "units_remaining": remaining}

@app.get("/api/process")
async def process_video_get(request: Request, user: dict = Depends(get_current_user)):
    fresh = get_user_by_id(user["id"])
    return {"units_balance": fresh["units_balance"], "ad_available": is_ad_available(request.client.host, user["id"]),
        "ad_duration_seconds": AD_WATCH_DURATION_SECONDS}

@app.get("/api/status/{task_id}")
async def get_status(task_id: str):
    with tasks_db_lock:
        if task_id not in tasks_db:
            raise HTTPException(status_code=404, detail="Task not found")
        return dict(tasks_db[task_id])

@app.get("/api/download/{task_id}")
async def download_video(task_id: str):
    with tasks_db_lock:
        if task_id not in tasks_db:
            raise HTTPException(status_code=404, detail="Task not found")
        task_info = dict(tasks_db[task_id])
    if task_info["status"] != "completed":
        raise HTTPException(status_code=400, detail="Video not ready yet.")
    file_path = task_info["file"]
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found on server")
    return FileResponse(path=file_path, filename=f"TiBe_Processed_{task_id}.mp4",
        media_type="video/mp4", content_disposition_type="attachment")

@app.get("/api/downloads/history")
async def get_download_history(user: dict = Depends(get_current_user)):
    with db_lock:
        rows = db.execute("SELECT id, task_id, url, quality, enhanced, units_spent, ad_watch_id, file_size_bytes, created_at FROM downloads WHERE user_id = ? ORDER BY created_at DESC LIMIT 50",
            (user["id"],)).fetchall()
    return {"downloads": [dict(r) for r in rows]}

app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
