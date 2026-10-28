// ===== Expo Connect shared script =====
// Live site par backend usi address se chalta hai (khali rehta hai). Laptop par Live Server (port 5500) se kholo to backend 8000 par jaata hai.
const API_BASE = (location.protocol === "file:" || (["localhost","127.0.0.1"].includes(location.hostname) && location.port !== "8000")) ? "http://127.0.0.1:8000" : "";
const WHATSAPP_LINK = "https://chat.whatsapp.com/LfkAuGKCxLBECXQHGSWQng?s=cl&p=a&mlu=4&ilr=4&iam=2"; // apna WhatsApp community link

const page = document.body.dataset.page || "";
const nav = [["index.html","Home","home"],["jobs.html","Find Jobs","jobs"],["status.html","My Status","status"],["join.html","Register","join"]];
document.getElementById("hdr").innerHTML = `<header><div class="wrap"><a class="logo" href="index.html">Expo<b>Connect</b></a><nav aria-label="Main">${
  nav.map(([h,t,k])=>`<a href="${h}" class="${k===page?"on":""}${k==="join"?" cta":""}">${t}</a>`).join("")}</nav></div></header>`;
document.getElementById("ftr").innerHTML = `<footer><div class="wrap"><div><b>Expo Connect</b><br>Event staffing, simplified.</div><div><a href="${WHATSAPP_LINK}">WhatsApp Community</a> &nbsp; <a href="privacy-policy.html">Privacy</a> &nbsp; <a href="terms.html">Terms</a></div></div></footer>`;

// ---------- Helpers ----------
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fmt = d => new Date(d + "T00:00").toLocaleDateString("en-IN", {day:"numeric", month:"short", year:"numeric"});
const money = n => "₹" + Number(n).toLocaleString("en-IN");
const payText = j => (j.pay_min && j.pay_max) ? `${money(j.pay_min)} – ${money(j.pay_max)}/day`
  : (j.pay_min || j.pay_max) ? `${money(j.pay_min || j.pay_max)}/day` : "Pay: jaldi batayenge";

const jobCard = j => {
  const place = [j.venue, j.city].filter(Boolean).map(esc).join(", ");
  const when = [fmt(j.event_date), j.duty_hours ? esc(j.duty_hours) : ""].filter(Boolean).join(" · ");
  const extra = [j.vacancies ? `${esc(j.vacancies)} vacancies` : "", j.eligibility ? esc(j.eligibility) : ""].filter(Boolean).join(" · ");
  return `<article class="card">${j.category ? `<span class="tag">${esc(j.category)}</span>` : ""}<h3>${esc(j.title)}</h3><div class="meta">${esc(j.event_name)} · ${place}</div><div class="meta">${when}</div><div class="pay">${payText(j)}</div>${extra ? `<div class="meta">${extra}</div>` : ""}<a class="btn btn-n" href="join.html?job=${encodeURIComponent(j.id)}">Apply Now</a></article>`;
};

const emptyBox = msg => `<div class="empty" style="grid-column:1/-1">${msg}</div>`;

// ---------- Jobs from backend (sirf active aur expire na hui) ----------
let jobsPromise = null;
const loadJobs = () => jobsPromise || (jobsPromise = fetch(API_BASE + "/api/jobs").then(r => { if (!r.ok) throw 0; return r.json(); }));

const feat = document.getElementById("featured");
if (feat) loadJobs()
  .then(js => { feat.innerHTML = js.length ? js.slice(0, 3).map(jobCard).join("") : emptyBox("Abhi koi active job nahi hai. Nayi jobs ke liye WhatsApp community join karo."); })
  .catch(() => { feat.innerHTML = emptyBox("Jobs load nahi ho payi. Thodi der baad dobara try karo."); });

const list = document.getElementById("jobList");
if (list) {
  const ven = document.getElementById("fVenue"), cat = document.getElementById("fCat"), from = document.getElementById("fDate");
  loadJobs().then(jobs => {
    [...new Set(jobs.map(j => j.venue).filter(Boolean))].sort().forEach(c => ven.add(new Option(c, c)));
    [...new Set(jobs.map(j => j.category).filter(Boolean))].sort().forEach(c => cat.add(new Option(c, c)));
    const draw = () => {
      const r = jobs.filter(j => (!ven.value || j.venue === ven.value) && (!cat.value || j.category === cat.value) && (!from.value || j.event_date >= from.value));
      list.innerHTML = r.length ? r.map(jobCard).join("") : emptyBox("Is filter par koi job nahi mili. Filter badal kar dekho ya WhatsApp community join karo.");
    };
    [ven, cat, from].forEach(e => e.addEventListener("input", draw));
    draw();
  }).catch(() => { list.innerHTML = emptyBox("Jobs load nahi ho payi. Thodi der baad dobara try karo."); });
}

// ---------- Register / Apply ----------
const jobId = new URLSearchParams(location.search).get("job");

const jn = document.getElementById("jobNote");
if (jn && jobId) loadJobs().then(js => {
  const jb = js.find(j => j.id === jobId);
  if (jb) jn.innerHTML = `Applying for: <b>${esc(jb.title)}</b> – ${esc(jb.event_name)}${jb.venue ? ", " + esc(jb.venue) : ""}`;
}).catch(() => {});

document.querySelectorAll("form[data-endpoint]").forEach(f => f.addEventListener("submit", async e => {
  e.preventDefault();
  const fd = Object.fromEntries(new FormData(f));
  const venues = [...f.querySelectorAll('input[name="venues"]:checked')].map(i => i.value);
  const data = {
    full_name: fd.name,
    phone: fd.phone,
    email: fd.email || null,
    age: fd.age ? Number(fd.age) : null,
    role: fd.role || null,
    experience: fd.experience || null,
    availability: fd.availability || null,
    preferred_venues: venues.join(", ") || null,
    pin: fd.pin || null,
    job_id: jobId || null
  };
  const ok = document.getElementById("ok"), btn = f.querySelector("button[type=submit]");
  btn.disabled = true;
  try {
    const r = await fetch(API_BASE + "/api/register", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(data)});
    if (!r.ok) { const err = await r.json().catch(() => ({})); throw err.detail; }
    const out = await r.json().catch(() => ({}));
    try { if (out.token) localStorage.setItem("ec_token", out.token); } catch (e) {}
    ok.style.display = "block"; f.reset();
  } catch (msg) {
    alert(typeof msg === "string" ? msg : "Submit nahi hua. Internet check karke dobara try karo.");
  }
  btn.disabled = false;
}));
