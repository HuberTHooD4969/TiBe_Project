import os
# Manual .env loader (no external dependency)
_env_loaded = False
def _load_env():
    global _env_loaded
    if _env_loaded:
        return
    _env_loaded = True
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip().strip("\"'")
                os.environ.setdefault(key, val)
_load_env()
import uuid
import sqlite3
try:
    import psycopg2
    import psycopg2.extras
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False
import json
import time
import threading
import subprocess
from urllib.parse import urlparse
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from fastapi import FastAPI, BackgroundTasks, HTTPException, Request, Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel, field_validator
from jose import JWTError, jwt as jose_jwt
import hashlib
import secrets
import re

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is required. Set it in .env or export it.")
IS_POSTGRES = DATABASE_URL.startswith("postgresql://") and HAS_PSYCOPG2
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY environment variable is required. Set it in .env or export it.")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))
PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY", "")
PAYSTACK_PUBLIC_KEY = os.getenv("PAYSTACK_PUBLIC_KEY", "")
AD_WATCH_DURATION_SECONDS = int(os.getenv("AD_WATCH_DURATION_SECONDS", "30"))
AD_WATCH_COOLDOWN_MINUTES = int(os.getenv("AD_WATCH_COOLDOWN_MINUTES", "60"))

RESOLUTION_COST = {"720p": 0, "1080p": 0, "2K": 2, "4K": 4}
PRICING_PLANS_JSON = os.getenv("PRICING_PLANS", json.dumps([
    {"name": "Starter", "units": 10, "price_cents": 499, "popular": False},
    {"name": "Pro", "units": 30, "price_cents": 1299, "popular": True},
    {"name": "Ultra", "units": 100, "price_cents": 3999, "popular": False},
]))
SUBSCRIPTION_PLANS_JSON = os.getenv("SUBSCRIPTION_PLANS", json.dumps([
    {"name": "Basic Monthly", "units": 20, "price_cents": 799, "popular": False},
    {"name": "Pro Monthly", "units": 60, "price_cents": 1999, "popular": True},
    {"name": "Unlimited Monthly", "units": 200, "price_cents": 4999, "popular": False},
]))
MAX_FRAME_WORKERS = int(os.getenv("MAX_FRAME_WORKERS", str(os.cpu_count() or 4)))
paystack_plan_codes = {}
paystack_plan_codes_lock = threading.Lock()

def _ps_currency():
    """Detect Paystack account currency by checking balance endpoint."""
    return "GHS"  # The user's test key only supports GHS

def _ps_amount(usd_cents):
    """Convert USD cents to Paystack's currency subunit."""
    if _ps_currency() == "GHS":
        rate = CURRENCY_RATES.get("GHS", {}).get("rate", 15.8)
        return int((usd_cents / 100) * rate * 100)
    return usd_cents  # USD cents for USD currency



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
    to_encode.update({"exp": expire, "type": "access"})
    return jose_jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def create_refresh_token(data: dict):
    d = data.copy()
    d["type"] = "refresh"
    return create_access_token(d, expires_delta=timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS))

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

class Database:
    def __init__(self, url):
        self.url = url
        self.is_pg = url.startswith("postgresql://") and HAS_PSYCOPG2
        if self.is_pg:
            self._conn = psycopg2.connect(url, connect_timeout=5)
            self._conn.autocommit = False
        else:
            self._conn = sqlite3.connect("tibe.db", check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
    def _sql(self, sql):
        if self.is_pg:
            sql = sql.replace("?", "%s")
            sql = re.sub(r"datetime\('now'\s*,\s*'\+?([^']+)'\)", r"(NOW() + INTERVAL '\1')", sql)
            sql = re.sub(r"datetime\('now'\)", "NOW()", sql)
        return sql
    def execute(self, sql, params=None):
        if self.is_pg:
            cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(self._sql(sql), params)
            return cur
        cur = self._conn.execute(sql, params or ())
        return cur
    def commit(self):
        self._conn.commit()
    def rollback(self):
        self._conn.rollback()

def get_db():
    db = Database(DATABASE_URL)
    if not db.is_pg:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=5000")
        db._conn.executescript("""
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
                expires_at TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS rate_limits (
                ip TEXT NOT NULL, endpoint TEXT NOT NULL, timestamp REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS subscriptions (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL UNIQUE,
                plan_name TEXT NOT NULL, paystack_subscription_code TEXT,
                paystack_customer_code TEXT, units_per_month INTEGER NOT NULL,
                monthly_price_cents INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                current_period_start TEXT, current_period_end TEXT,
                cancelled_at TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            CREATE INDEX IF NOT EXISTS idx_rate_limits_ip ON rate_limits(ip, timestamp);
            CREATE INDEX IF NOT EXISTS idx_ad_watches_ip ON ad_watches(ip_address, completed_at);
            CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions(user_id);
            CREATE INDEX IF NOT EXISTS idx_downloads_user ON downloads(user_id);
            CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions(user_id);
        """)
    else:
        db.execute("""CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL, units_balance INTEGER NOT NULL DEFAULT 0,
            is_premium INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS transactions (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
            amount_cents INTEGER NOT NULL, currency TEXT NOT NULL DEFAULT 'usd',
            provider TEXT NOT NULL, provider_txn_id TEXT,
            units_added INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS downloads (
            id TEXT PRIMARY KEY, user_id TEXT, task_id TEXT UNIQUE,
            url TEXT NOT NULL, quality TEXT NOT NULL DEFAULT '1080p',
            enhanced INTEGER NOT NULL DEFAULT 0, units_spent INTEGER NOT NULL DEFAULT 0,
            ad_watch_id TEXT, file_size_bytes INTEGER DEFAULT 0,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS ad_watches (
            id TEXT PRIMARY KEY, user_id TEXT, ip_address TEXT,
            completed_at TIMESTAMP NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMP NOT NULL, FOREIGN KEY (user_id) REFERENCES users(id)
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS rate_limits (
            ip TEXT NOT NULL, endpoint TEXT NOT NULL, timestamp DOUBLE PRECISION NOT NULL
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS subscriptions (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL UNIQUE,
            plan_name TEXT NOT NULL, paystack_subscription_code TEXT,
            paystack_customer_code TEXT, units_per_month INTEGER NOT NULL,
            monthly_price_cents INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            current_period_start TIMESTAMP, current_period_end TIMESTAMP,
            cancelled_at TIMESTAMP, created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_rate_limits_ip ON rate_limits(ip, timestamp)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_ad_watches_ip ON ad_watches(ip_address, completed_at)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions(user_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_downloads_user ON downloads(user_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions(user_id)")
    # Add 'used' column to ad_watches if missing (migration)
    try:
        db.execute("ALTER TABLE ad_watches ADD COLUMN used INTEGER NOT NULL DEFAULT 0")
        db.commit()
    except Exception:
        pass
    return db

db = get_db()

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

def deduct_unit(user_id: str, count: int = 1) -> int:
    with db_lock:
        row = db.execute("SELECT units_balance FROM users WHERE id = ?", (user_id,)).fetchone()
        if row and row["units_balance"] >= count:
            db.execute("UPDATE users SET units_balance = units_balance - ? WHERE id = ?", (count, user_id))
            db.commit()
            return row["units_balance"] - count
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

def get_user_subscription(user_id):
    with db_lock:
        row = db.execute("SELECT * FROM subscriptions WHERE user_id = ? AND status = 'active'", (user_id,)).fetchone()
        return dict(row) if row else None

def create_subscription_record(user_id, plan_name, sub_code, cust_code, units, price_cents):
    with db_lock:
        existing = db.execute("SELECT id FROM subscriptions WHERE user_id = ?", (user_id,)).fetchone()
        if existing:
            db.execute("""UPDATE subscriptions SET plan_name=?, paystack_subscription_code=?,
                paystack_customer_code=?, units_per_month=?, monthly_price_cents=?, status='active',
                current_period_start=datetime('now'), current_period_end=datetime('now','+1 month'),
                cancelled_at=NULL WHERE user_id=?""",
                (plan_name, sub_code, cust_code, units, price_cents, user_id))
        else:
            sub_id = str(uuid.uuid4())
            db.execute("""INSERT INTO subscriptions (id, user_id, plan_name, paystack_subscription_code,
                paystack_customer_code, units_per_month, monthly_price_cents, status,
                current_period_start, current_period_end) VALUES (?, ?, ?, ?, ?, ?, ?, 'active',
                datetime('now'), datetime('now','+1 month'))""",
                (sub_id, user_id, plan_name, sub_code, cust_code, units, price_cents))
        db.commit()

def cancel_subscription_record(user_id):
    with db_lock:
        db.execute("""UPDATE subscriptions SET status='cancelled', cancelled_at=datetime('now')
            WHERE user_id=? AND status='active'""", (user_id,))
        db.commit()

def has_transaction(reference):
    with db_lock:
        return db.execute("SELECT id FROM transactions WHERE provider_txn_id = ?", (reference,)).fetchone() is not None

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
        hostname = (parsed.hostname or "").lower()
        if not hostname:
            return False
        import socket
        try:
            addrs = socket.getaddrinfo(hostname, 80)
            for family, _, _, _, sockaddr in addrs:
                ip = sockaddr[0]
                if ip.startswith("127.") or ip.startswith("10.") or ip.startswith("192.168.") or ip.startswith("172.16.") or ip.startswith("0.") or ip == "::1" or ip == "0.0.0.0":
                    return False
                parts = ip.split(".")
                if len(parts) == 4:
                    try:
                        if int(parts[0]) == 169 and int(parts[1]) == 254:
                            return False
                    except ValueError:
                        pass
        except Exception:
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

class SubscribeRequest(BaseModel):
    plan_name: str

async def ensure_paystack_plans():
    # Paystack plans are optional (for production auto-renewals).
    # In test mode we skip plan creation and handle subscriptions via direct transactions.
    pass

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await ensure_paystack_plans()
    except Exception:
        pass
    yield

app = FastAPI(title="TiBe Web API", description="Backend for TiBe Video Processing SaaS", lifespan=lifespan, version="2.0.0")

_allowed_origins = os.getenv("CORS_ORIGINS", "http://localhost:8000,http://localhost:3000")
app.add_middleware(CORSMiddleware, allow_origins=_allowed_origins.split(","), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
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
async def register(req: RegisterRequest, request: Request = None):
    if request and not check_rate_limit(request.client.host, "/api/auth/register"):
        raise HTTPException(status_code=429, detail="Too many registration attempts. Please slow down.")
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
async def login(req: LoginRequest, request: Request = None):
    if request and not check_rate_limit(request.client.host, "/api/auth/login"):
        raise HTTPException(status_code=429, detail="Too many login attempts. Please slow down.")
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
    token_type = payload.get("type", "")
    if token_type != "refresh":
        raise HTTPException(status_code=401, detail="Not a refresh token")
    user_id = payload.get("sub")
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    access_token = create_access_token({"sub": user["id"]})
    new_refresh = create_refresh_token({"sub": user["id"], "type": "refresh"})
    return {"access_token": access_token, "refresh_token": new_refresh, "token_type": "bearer"}

@app.get("/api/user/me")
async def get_me(user: dict = Depends(get_current_user)):
    fresh = get_user_by_id(user["id"])
    sub = get_user_subscription(user["id"])
    sub_info = None
    if sub:
        sub_info = {k: sub[k] for k in ["plan_name", "units_per_month", "monthly_price_cents",
            "status", "current_period_end", "created_at"]}
    return {"id": fresh["id"], "email": fresh["email"], "units_balance": fresh["units_balance"],
        "is_premium": bool(fresh["is_premium"]), "created_at": fresh["created_at"],
        "subscription": sub_info}

# --- Pricing & Currency ---
@app.get("/api/pricing")
async def get_pricing():
    return {"plans": get_pricing_plans(), "subscription_plans": json.loads(SUBSCRIPTION_PLANS_JSON),
        "currencies": CURRENCY_RATES, "locale_currency_map": LOCALE_CURRENCY,
        "resolution_costs": RESOLUTION_COST}

@app.get("/api/currencies")
async def get_currencies():
    return {"currencies": CURRENCY_RATES, "locale_currency_map": LOCALE_CURRENCY,
        "resolution_costs": RESOLUTION_COST}

# --- Paystack ---
@app.post("/api/payment/paystack/initialize")
async def paystack_initialize(req: PaystackInitializeRequest, request: Request, user: dict = Depends(get_current_user)):
    if not PAYSTACK_SECRET_KEY:
        raise HTTPException(status_code=501, detail="Paystack not configured. Set PAYSTACK_SECRET_KEY.")
    plans = get_pricing_plans()
    matching = [p for p in plans if p["units"] == req.plan_units and p["price_cents"] == req.amount_cents]
    if not matching:
        raise HTTPException(status_code=400, detail="Invalid plan_units/amount_cents combination")
    import httpx
    base_url = str(request.base_url).rstrip("/")
    callback_url = base_url + "/?trxref={reference}"
    ps_currency = _ps_currency()
    ps_amount = _ps_amount(req.amount_cents)
    async with httpx.AsyncClient() as client:
        resp = await client.post("https://api.paystack.co/transaction/initialize", json={
            "email": user["email"], "amount": str(ps_amount), "currency": ps_currency,
            "callback_url": callback_url, "metadata": {"user_id": user["id"], "units": req.plan_units,
                "type": "onetime"}},
            headers={"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}", "Content-Type": "application/json"})
        data = resp.json()
        if not data.get("status"):
            raise HTTPException(status_code=400, detail=f"Paystack error: {data.get('message', 'Unknown')}")
        return {"authorization_url": data["data"]["authorization_url"], "reference": data["data"]["reference"]}

@app.get("/api/payment/paystack/verify")
async def paystack_verify(reference: str = "", user: dict = Depends(get_current_user)):
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
            if user_id != user["id"]:
                raise HTTPException(status_code=403, detail="Transaction does not belong to this user")
            units = int(metadata.get("units", 0))
            amount_cents = tx_data.get("amount", 0)
            with db_lock:
                if has_transaction(reference):
                    return {"status": "success", "units_added": 0, "amount": amount_cents, "already_processed": True}
                add_units(user_id, units)
                create_transaction(user_id, amount_cents, "paystack", reference, units)
                if metadata.get("type") == "subscription":
                    plan_name = metadata.get("plan_name", "")
                    cust_code = tx_data.get("customer", {}).get("customer_code", "")
                    create_subscription_record(user_id, plan_name, "", cust_code, units, amount_cents)
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
    if not hmac.compare_digest(sig, expected_sig):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")
    event = json.loads(body)
    if event.get("event") == "charge.success":
        tx_data = event["data"]
        metadata = tx_data.get("metadata", {})
        user_id = metadata.get("user_id")
        units = int(metadata.get("units", 0))
        reference = tx_data.get("reference", "")
        if user_id and units > 0 and not has_transaction(reference):
            add_units(user_id, units)
            create_transaction(user_id, tx_data.get("amount", 0), "paystack", reference, units)
            if metadata.get("type") == "subscription":
                plan_name = metadata.get("plan_name", "")
                cust_code = tx_data.get("customer", {}).get("customer_code", "")
                sub_data = tx_data.get("subscription")
                sub_code = sub_data.get("subscription_code", "") if sub_data else ""
                if not get_user_subscription(user_id):
                    create_subscription_record(user_id, plan_name, sub_code, cust_code, units, tx_data.get("amount", 0))
    elif event.get("event") == "subscription.not_renew":
        sub_data = event["data"]
        sub_code = sub_data.get("subscription_code", "")
        if sub_code:
            with db_lock:
                db.execute("UPDATE subscriptions SET status='cancelled', cancelled_at=datetime('now') WHERE paystack_subscription_code=?", (sub_code,))
                db.commit()
    elif event.get("event") == "invoice.updated":
        inv_data = event["data"]
        if inv_data.get("paid"):
            cust_email = inv_data.get("customer", {}).get("email", "")
            sub_code = inv_data.get("subscription", {}).get("subscription_code", "")
            if sub_code:
                with db_lock:
                    sub_row = db.execute("SELECT * FROM subscriptions WHERE paystack_subscription_code=? AND status='active'", (sub_code,)).fetchone()
                if sub_row:
                    user_id = sub_row["user_id"]
                    # Get transaction for this invoice to add units
                    txn_ref = inv_data.get("transaction", {})
                    if txn_ref:
                        ref = txn_ref.get("reference", "")
                        if not has_transaction(ref):
                            add_units(user_id, sub_row["units_per_month"])
                            create_transaction(user_id, inv_data.get("amount", 0), "paystack", ref, sub_row["units_per_month"])
                            with db_lock:
                                db.execute("""UPDATE subscriptions SET current_period_start=datetime('now'),
                                    current_period_end=datetime('now','+1 month') WHERE id=?""", (sub_row["id"],))
                                db.commit()
    return {"status": "ok"}

# --- Subscription Endpoints ---
@app.post("/api/payment/paystack/subscribe")
async def paystack_subscribe(req: SubscribeRequest, request: Request, user: dict = Depends(get_current_user)):
    if not PAYSTACK_SECRET_KEY:
        raise HTTPException(status_code=501, detail="Paystack not configured")
    plans = json.loads(SUBSCRIPTION_PLANS_JSON)
    plan = next((p for p in plans if p["name"] == req.plan_name), None)
    if not plan:
        raise HTTPException(status_code=400, detail="Invalid plan name")
    existing_sub = get_user_subscription(user["id"])
    if existing_sub:
        raise HTTPException(status_code=400, detail="You already have an active subscription")
    # Initialize a direct transaction (no Paystack plan — plans require specific currencies in test mode).
    # Subscription record is created on first successful payment.
    import httpx
    callback_url = str(request.base_url).rstrip("/") + "/?trxref={reference}"
    ps_currency = _ps_currency()
    ps_amount = _ps_amount(plan["price_cents"])
    async with httpx.AsyncClient() as client:
        resp = await client.post("https://api.paystack.co/transaction/initialize", json={
            "email": user["email"], "amount": str(ps_amount), "currency": ps_currency,
            "callback_url": callback_url,
            "metadata": {"user_id": user["id"], "plan_name": plan["name"],
                "units": plan["units"], "type": "subscription"}},
            headers={"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}", "Content-Type": "application/json"})
        data = resp.json()
        if not data.get("status"):
            raise HTTPException(status_code=400, detail=f"Paystack error: {data.get('message', 'Unknown')}")
        return {"authorization_url": data["data"]["authorization_url"], "reference": data["data"]["reference"]}

@app.get("/api/subscription")
async def get_subscription(user: dict = Depends(get_current_user)):
    sub = get_user_subscription(user["id"])
    if not sub:
        return {"subscription": None}
    return {"subscription": {
        "plan_name": sub["plan_name"], "units_per_month": sub["units_per_month"],
        "monthly_price_cents": sub["monthly_price_cents"],
        "status": sub["status"], "current_period_end": sub["current_period_end"],
        "created_at": sub["created_at"]
    }}

@app.post("/api/subscription/cancel")
async def cancel_subscription(user: dict = Depends(get_current_user)):
    sub = get_user_subscription(user["id"])
    if not sub:
        raise HTTPException(status_code=404, detail="No active subscription found")
    sub_code = sub.get("paystack_subscription_code")
    manage_url = ""
    if sub_code and PAYSTACK_SECRET_KEY:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"https://api.paystack.co/subscription/{sub_code}/manage/link",
                headers={"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"})
            if resp.status_code == 200:
                manage_url = resp.json().get("data", {}).get("link", "")
    cancel_subscription_record(user["id"])
    return {"status": "cancelled", "message": "Your subscription has been cancelled. No further charges will be made.",
        "manage_url": manage_url}

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
    import cv2
    import numpy as np
    from concurrent.futures import ThreadPoolExecutor, as_completed
    if num_workers is None:
        num_workers = min(MAX_FRAME_WORKERS, 2)
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

    def process_frame(frame):
        frame = cv2.fastNlMeansDenoisingColored(frame, None, 10, 10, 7, 21)
        frame = cv2.detailEnhance(frame, sigma_s=10, sigma_r=0.15)
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        l = cv2.equalizeHist(l)
        frame = cv2.merge((l, a, b))
        frame = cv2.cvtColor(frame, cv2.COLOR_LAB2BGR)
        return frame

    CHUNK = max(1, min(30, total_frames // (num_workers * 2)))
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        frames_batch = []
        frame_idx = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            frames_batch.append(frame)
            frame_idx += 1
            if len(frames_batch) >= CHUNK:
                results = list(executor.map(process_frame, frames_batch))
                for r in results:
                    out.write(r)
                frames_batch = []
                progress = 50 + int(45 * frame_idx / total_frames)
                with tasks_db_lock:
                    if task_id in tasks_db:
                        tasks_db[task_id]["progress"] = progress
        if frames_batch:
            results = list(executor.map(process_frame, frames_batch))
            for r in results:
                out.write(r)
    cap.release()
    out.release()

def process_video_task(task_id: str, request: VideoRequest, user=None, units_spent=0):
    import yt_dlp
    import imageio_ffmpeg
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
            record_download(user["id"], task_id, request.url, request.quality, request.ultra_enhance, units_spent=units_spent, file_size=file_size)
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
    quality = video_request.quality
    if quality not in RESOLUTION_COST:
        raise HTTPException(status_code=400, detail=f"Invalid quality '{quality}'. Must be one of: {', '.join(RESOLUTION_COST.keys())}")
    unit_cost = RESOLUTION_COST[quality]
    ad_watch_id = request.headers.get("X-Ad-Watch-Id")

    if unit_cost == 0:
        if ad_watch_id:
            with db_lock:
                watch = db.execute("SELECT id FROM ad_watches WHERE id = ? AND expires_at > datetime('now') AND used = FALSE", (ad_watch_id,)).fetchone()
            if not watch:
                raise HTTPException(status_code=400, detail="Invalid or expired ad watch. Please watch the ad again.")
            with db_lock:
                db.execute("UPDATE ad_watches SET used = TRUE WHERE id = ?", (ad_watch_id,))
                db.commit()
        else:
            raise HTTPException(status_code=400, detail="Free resolutions (720p/1080p) require watching an ad first.")
        units_spent = 0
        remaining = user["units_balance"]
    else:
        if user["units_balance"] >= unit_cost:
            remaining = deduct_unit(user["id"], unit_cost)
            if remaining < 0:
                raise HTTPException(status_code=402, detail="No units remaining.")
            units_spent = unit_cost
        else:
            raise HTTPException(status_code=402, detail=f"Insufficient units for {quality}. You need {unit_cost} units but have {user['units_balance']}. Please buy more units or subscribe.")

    task_id = str(uuid.uuid4())
    background_tasks.add_task(process_video_task, task_id, video_request, user, units_spent)
    return {"task_id": task_id, "message": "Video processing started.", "units_remaining": remaining, "unit_cost": unit_cost, "units_spent": units_spent}

@app.get("/api/process")
async def process_video_get(request: Request, user: dict = Depends(get_current_user)):
    fresh = get_user_by_id(user["id"])
    return {"units_balance": fresh["units_balance"], "ad_available": is_ad_available(request.client.host, user["id"]),
        "ad_duration_seconds": AD_WATCH_DURATION_SECONDS, "resolution_costs": RESOLUTION_COST}

@app.get("/api/status/{task_id}")
async def get_status(task_id: str, user: dict = Depends(get_current_user)):
    with tasks_db_lock:
        if task_id not in tasks_db:
            raise HTTPException(status_code=404, detail="Task not found")
        return dict(tasks_db[task_id])

@app.get("/api/download/{task_id}")
async def download_video(task_id: str, user: dict = Depends(get_current_user)):
    with db_lock:
        dl = db.execute("SELECT id FROM downloads WHERE task_id = ? AND user_id = ?", (task_id, user["id"])).fetchone()
    if not dl:
        raise HTTPException(status_code=404, detail="Download not found or not authorized")
    with tasks_db_lock:
        if task_id not in tasks_db:
            raise HTTPException(status_code=404, detail="Task not found on server (may have expired). Check your download history.")
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

@app.get("/api/health")
async def healthcheck():
    return {"status": "ok", "database": "postgresql" if IS_POSTGRES else "sqlite"}

app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
