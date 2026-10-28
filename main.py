import os, datetime, time
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
sb = create_client(URL, KEY)  # data ke liye (kabhi login mat karwana isse)

def auth_client():
    return create_client(URL, ANON)  # sirf login/token check ke liye (anon/publishable key)

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

HITS = {}
def limit(request: Request, max_hits=10, window=3600):
    ip = (request.headers.get("x-forwarded-for") or request.client.host).split(",")[0].strip()
    now = time.time()
    hits = [t for t in HITS.get(ip, []) if now - t < window]
    if len(hits) >= max_hits:
        raise HTTPException(429, "Bahut zyada koshish ho gayi. Thodi der baad try karo.")
    hits.append(now)
    HITS[ip] = hits

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
    limit(request)
    data = r.model_dump(exclude={"job_id"})
    cand = sb.table("candidates").upsert(data, on_conflict="phone").execute().data[0]
    if r.job_id:
        job = sb.table("jobs").select("id").eq("id", r.job_id).eq("status", "active").execute().data
        if not job:
            raise HTTPException(400, "Job available nahi hai")
        old = sb.table("applications").select("id").eq("job_id", r.job_id).eq("candidate_id", cand["id"]).execute().data
        if not old:
            sb.table("applications").insert({"job_id": r.job_id, "candidate_id": cand["id"]}).execute()
    return {"ok": True}

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
