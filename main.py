import os, datetime, time, hmac, hashlib, base64, json, secrets
from typing import Optional
from fastapi import FastAPI, HTTPException, Header, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
URL = os.environ["SUPABASE_URL"].strip().rstrip("/")
KEY = os.environ["SUPABASE_SERVICE_KEY"].strip()
ADMIN_EMAIL = os.environ["ADMIN_EMAIL"].strip().lower()
ANON = os.environ["SUPABASE_ANON_KEY"].strip()
SECRET = hashlib.sha256(("tok:" + KEY).encode()).digest()
sb = create_client(URL, KEY)  # data ke liye (kabhi login mat karwana isse)

def auth_client():
    return create_client(URL, ANON)  # sirf login/token check ke liye (anon/publishable key)

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

HITS = {}
def limit(key, max_hits=10, window=3600):
    now = time.time()
    hits = [t for t in HITS.get(key, []) if now - t < window]
    if len(hits) >= max_hits:
        raise HTTPException(429, "Bahut zyada koshish ho gayi. Thodi der baad try karo.")
    hits.append(now)
    HITS[key] = hits

def client_ip(request: Request):
    return (request.headers.get("x-forwarded-for") or request.client.host).split(",")[0].strip()

def hash_pin(pin, salt=None):
    salt = salt or secrets.token_hex(8)
    h = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), 100_000).hex()
    return salt + "$" + h

def check_pin(pin, stored):
    try:
        salt = stored.split("$")[0]
        return hmac.compare_digest(hash_pin(pin, salt), stored)
    except Exception:
        return False

def make_token(cid):
    body = base64.urlsafe_b64encode(json.dumps({"c": cid, "e": int(time.time()) + 7 * 86400}).encode()).decode()
    return body + "." + hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest()

def me(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Login required")
    try:
        body, sig = authorization[7:].split(".")
        if not hmac.compare_digest(sig, hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest()):
            raise ValueError
        d = json.loads(base64.urlsafe_b64decode(body))
        if d["e"] < time.time():
            raise ValueError
        return d["c"]
    except Exception:
        raise HTTPException(401, "Login required")

class Job(BaseModel):
    title: str
    event_name: str
    city: str
    venue: Optional[str] = None
    category: Optional[str] = None
    event_date: str
    duty_hours: Optional[str] = None
    pay_min: Optional[int] = None
    pay_max: Optional[int] = None
    vacancies: Optional[int] = 1
    eligibility: Optional[str] = None

class Reg(BaseModel):
    full_name: str
    phone: str
    email: Optional[str] = None
    city: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    experience: Optional[str] = None
    role: Optional[str] = None
    availability: Optional[str] = None
    preferred_venues: Optional[str] = None
    pin: Optional[str] = None
    job_id: Optional[str] = None

class Login(BaseModel):
    email: str
    password: str

class Patch(BaseModel):
    status: str

def admin(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Login required")
    try:
        user = auth_client().auth.get_user(authorization[7:]).user
    except Exception as e:
        print("TOKEN ERROR:", e)
        raise HTTPException(401, "Invalid token")
    if not user or (user.email or "").lower() != ADMIN_EMAIL:
        raise HTTPException(403, "Not admin")

# ---------- Public ----------
@app.get("/api/jobs")
def public_jobs():
    today = datetime.date.today().isoformat()
    return sb.table("jobs").select("*").eq("status", "active").gte("event_date", today).order("event_date").execute().data

@app.post("/api/register")
def register(r: Reg, request: Request):
    limit("ip:" + client_ip(request))
    if not (r.pin and r.pin.isdigit() and len(r.pin) == 6):
        raise HTTPException(400, "6 ank ka PIN daalo.")
    ex = sb.table("candidates").select("id,pin_hash").eq("phone", r.phone).execute().data
    if ex and ex[0].get("pin_hash"):
        limit("pin:" + r.phone, 8, 3600)
        if not check_pin(r.pin, ex[0]["pin_hash"]):
            raise HTTPException(403, "Is number se pehle registration ho chuka hai. Sahi PIN daalo.")
    data = r.model_dump(exclude={"job_id", "pin"})
    data["pin_hash"] = hash_pin(r.pin)
    cand = sb.table("candidates").upsert(data, on_conflict="phone").execute().data[0]
    if r.job_id:
        job = sb.table("jobs").select("id").eq("id", r.job_id).eq("status", "active").execute().data
        if not job:
            raise HTTPException(400, "Job available nahi hai")
        old = sb.table("applications").select("id").eq("job_id", r.job_id).eq("candidate_id", cand["id"]).execute().data
        if not old:
            sb.table("applications").insert({"job_id": r.job_id, "candidate_id": cand["id"]}).execute()
    return {"ok": True, "token": make_token(cand["id"])}

class CLogin(BaseModel):
    phone: str
    pin: str

@app.post("/api/candidate/login")
def candidate_login(b: CLogin, request: Request):
    limit("ip:" + client_ip(request), 20, 3600)
    limit("pin:" + b.phone.strip(), 8, 3600)
    row = sb.table("candidates").select("id,pin_hash,full_name").eq("phone", b.phone.strip()).execute().data
    if not row or not row[0].get("pin_hash") or not check_pin(b.pin, row[0]["pin_hash"]):
        raise HTTPException(401, "Phone number ya PIN galat hai")
    return {"token": make_token(row[0]["id"]), "name": row[0]["full_name"]}

@app.get("/api/candidate/applications")
def my_applications(cid: str = Depends(me)):
    return sb.table("applications").select("id,status,created_at,jobs(title,event_name,venue,city,event_date,duty_hours)").eq("candidate_id", cid).order("created_at", desc=True).execute().data

# ---------- Admin ----------
@app.post("/api/admin/login")
def login(b: Login):
    try:
        res = auth_client().auth.sign_in_with_password({"email": b.email.strip(), "password": b.password})
    except Exception as e:
        print("LOGIN ERROR:", e)
        raise HTTPException(401, "Email ya password galat")
    if (res.user.email or "").lower() != ADMIN_EMAIL:
        raise HTTPException(403, "Not admin")
    return {"token": res.session.access_token}

@app.get("/api/admin/jobs", dependencies=[Depends(admin)])
def admin_jobs():
    return sb.table("jobs").select("*").order("created_at", desc=True).execute().data

@app.post("/api/admin/jobs", dependencies=[Depends(admin)])
def add_job(j: Job):
    return sb.table("jobs").insert(j.model_dump()).execute().data[0]

@app.patch("/api/admin/jobs/{jid}", dependencies=[Depends(admin)])
def job_status(jid: str, p: Patch):
    if p.status not in ("active", "closed"):
        raise HTTPException(400, "bad status")
    return sb.table("jobs").update({"status": p.status}).eq("id", jid).execute().data

@app.get("/api/admin/applications", dependencies=[Depends(admin)])
def admin_apps():
    return sb.table("applications").select("*, jobs(title,event_name,event_date), candidates(full_name,phone,email,city,age,gender,experience,role,availability,preferred_venues)").order("created_at", desc=True).execute().data

@app.patch("/api/admin/applications/{aid}", dependencies=[Depends(admin)])
def app_status(aid: str, p: Patch):
    if p.status not in ("applied", "shortlisted", "selected", "rejected"):
        raise HTTPException(400, "bad status")
    return sb.table("applications").update({"status": p.status}).eq("id", aid).execute().data

@app.get("/admin")
def admin_page():
    return FileResponse(os.path.join(os.path.dirname(__file__), "admin.html"))

@app.get("/health")
def health():
    return {"status": "ok"}

# Website (frontend folder) isi server se chalti hai. Ye sabse neeche rehna chahiye.
SITE_DIR = os.path.join(os.path.dirname(__file__), "frontend")
if os.path.isdir(SITE_DIR):
    app.mount("/", StaticFiles(directory=SITE_DIR, html=True), name="site")
