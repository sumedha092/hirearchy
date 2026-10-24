"""Shared engine for job-sniper: fetch public job boards, filter, rank, store state.

Standard library only (runs in Cubbie's sandbox with no extra packages).
Ported from Sumedha's ai-job-agent (core.py, classify.py, bench/diff.py).
"""
from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("SKILL_DATA_DIR") or os.path.join(os.path.expanduser("~"), ".job-sniper")
os.makedirs(DATA_DIR, exist_ok=True)

UA = {"User-Agent": "job-sniper-cubbie-skill/1.0 (student project)", "Accept": "application/json"}
BOARD_TIMEOUT = 8          # seconds per HTTP request
NOW = lambda: dt.datetime.now(dt.timezone.utc)


# ------------------------------------------------------------------ http
def get_json(url, params=None, timeout=BOARD_TIMEOUT, tries=2):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and i + 1 < tries:
                last = e
                time.sleep(1.0)
                continue
            raise
        except Exception as e:  # timeouts, resets
            last = e
            if i + 1 < tries:
                time.sleep(0.5)
    raise last


# ------------------------------------------------------------------ helpers
def clean_html(s):
    if not s:
        return ""
    s = html.unescape(html.unescape(s))
    s = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>", "\n", s)
    s = re.sub(r"(?i)<li[^>]*>", "\n- ", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"[ \t\xa0]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n\n", s).strip()


def parse_date(v):
    if v in (None, ""):
        return None
    try:
        if isinstance(v, (int, float)):
            return dt.datetime.fromtimestamp(v / 1000 if v > 1e11 else v, dt.timezone.utc)
        d = dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)
    except Exception:
        return None


def iso(d):
    return d.isoformat(timespec="seconds") if d else None


def age_text(d):
    if not d:
        return "date unknown"
    h = (NOW() - d).total_seconds() / 3600
    if h < 1:
        return f"{max(1, int(h * 60))} min ago"
    if h < 48:
        return f"{int(h)}h ago"
    return f"{int(h // 24)}d ago"


def pretty_company(name):
    n = name.replace("-", " ").replace("_", " ")
    return n if any(c.isupper() for c in n) else n.title()


def _job(company, provider, jid, title, location, url, posted, desc):
    return {"id": f"{provider}:{jid}", "company": pretty_company(company), "provider": provider,
            "title": (title or "").strip(), "location": (location or "").strip(),
            "url": url or "", "posted": iso(posted), "description": desc or ""}


# ------------------------------------------------------------------ fetchers
def fetch_greenhouse(slug, name):
    # List without content (light), descriptions fetched later only for matches.
    data = get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
    out = []
    for j in data.get("jobs", []):
        posted = parse_date(j.get("first_published")) or parse_date(j.get("updated_at"))
        job = _job(name, "greenhouse", j.get("id"), j.get("title"),
                   (j.get("location") or {}).get("name"), j.get("absolute_url"), posted, "")
        job["_detail"] = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{j.get('id')}"
        out.append(job)
    return out


def fetch_lever(slug, name):
    data = get_json(f"https://api.lever.co/v0/postings/{slug}", {"mode": "json"})
    out = []
    for j in data:
        cats = j.get("categories") or {}
        loc = cats.get("location") or ""
        country = (j.get("country") or "").strip()
        if country and country.lower() not in loc.lower():
            loc = f"{loc}, {country}" if loc else country
        if (j.get("workplaceType") or "").lower() == "remote":
            loc = (loc + " (Remote)").strip()
        parts = [j.get("descriptionPlain") or ""]
        for lst in j.get("lists") or []:
            parts.append(lst.get("text", "") + "\n" + clean_html(lst.get("content", "")))
        parts.append(j.get("additionalPlain") or "")
        out.append(_job(name, "lever", j.get("id"), j.get("text"), loc, j.get("hostedUrl"),
                        parse_date(j.get("createdAt")), "\n".join(parts)))
    return out


def fetch_ashby(slug, name):
    data = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    out = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        loc = j.get("location") or ""
        sec = [x.get("location") for x in (j.get("secondaryLocations") or []) if x.get("location")]
        if sec:
            loc = "; ".join([loc] + sec)
        if j.get("isRemote"):
            loc = (loc + " (Remote)").strip()
        out.append(_job(name, "ashby", j.get("id") or j.get("jobUrl"), j.get("title"), loc,
                        j.get("jobUrl") or j.get("applyUrl"), parse_date(j.get("publishedAt")),
                        j.get("descriptionPlain") or clean_html(j.get("descriptionHtml"))))
    return out


def fetch_smartrecruiters(company_id, name, max_pages=5):
    out, offset = [], 0
    for _ in range(max_pages):
        data = get_json(f"https://api.smartrecruiters.com/v1/companies/{company_id}/postings",
                        {"limit": 100, "offset": offset})
        for j in data.get("content", []):
            loc = j.get("location") or {}
            locs = ", ".join(x for x in [loc.get("city"), loc.get("region"),
                                         (loc.get("country") or "").upper()] if x)
            if loc.get("remote"):
                locs += " (Remote)"
            job = _job(name, "smartrecruiters", j.get("id"), j.get("name"), locs,
                       f"https://jobs.smartrecruiters.com/{company_id}/{j.get('id')}",
                       parse_date(j.get("releasedDate")), "")
            job["_detail"] = f"https://api.smartrecruiters.com/v1/companies/{company_id}/postings/{j.get('id')}"
            out.append(job)
        offset += 100
        if offset >= data.get("totalFound", 0):
            break
    return out


FETCHERS = {"greenhouse": fetch_greenhouse, "lever": fetch_lever,
            "ashby": fetch_ashby, "smartrecruiters": fetch_smartrecruiters}


def load_boards(companies=None):
    with open(os.path.join(HERE, "boards.json")) as f:
        boards = json.load(f)
    extra = os.path.join(DATA_DIR, "extra_boards.json")
    if os.path.exists(extra):
        try:
            boards += json.load(open(extra))
        except Exception:
            pass
    if companies:
        want = [c.strip().lower().replace(" ", "") for c in companies if c.strip()]
        boards = [b for b in boards
                  if any(w in b["name"].lower().replace("-", "").replace(" ", "") or
                         w in b["board"].lower() for w in want)]
    return boards


def fetch_all(boards, workers=48, deadline=80):
    """Fetch boards in parallel. Stops waiting at `deadline` seconds and reports
    unfinished boards as skipped. Returns (jobs_by_board, report)."""
    start = time.time()
    by_board, report = {}, {"ok": 0, "failed": 0, "timed_out": 0, "failed_names": []}

    def one(b):
        return FETCHERS[b["provider"]](b["board"], b["name"])

    ex = ThreadPoolExecutor(workers)
    futs = {ex.submit(one, b): b for b in boards}
    pending = set(futs)
    while pending:
        left = deadline - (time.time() - start)
        if left <= 0:
            break
        done, pending = wait(pending, timeout=left, return_when=FIRST_COMPLETED)
        for f in done:
            b = futs[f]
            key = f"{b['provider']}:{b['board']}"
            try:
                by_board[key] = f.result()
                report["ok"] += 1
            except Exception as e:
                report["failed"] += 1
                report["failed_names"].append(f"{b['name']} ({str(e)[:40]})")
    report["timed_out"] = len(pending)
    ex.shutdown(wait=False, cancel_futures=True)
    report["seconds"] = round(time.time() - start, 1)
    return by_board, report


def fill_descriptions(jobs, workers=16, deadline=25):
    """Greenhouse/SmartRecruiters lists have no description; fetch them for the
    (few) jobs we are about to show."""
    need = [j for j in jobs if not j.get("description") and j.get("_detail")]
    if not need:
        return

    def one(j):
        d = get_json(j["_detail"])
        if j["provider"] == "greenhouse":
            return clean_html(d.get("content"))
        secs = ((d.get("jobAd") or {}).get("sections") or {})
        return "\n\n".join(clean_html((s or {}).get("text", "")) for s in secs.values())

    ex = ThreadPoolExecutor(workers)
    futs = {ex.submit(one, j): j for j in need}
    done, _ = wait(futs, timeout=deadline)
    for f in done:
        try:
            futs[f]["description"] = f.result() or ""
        except Exception:
            pass
    ex.shutdown(wait=False, cancel_futures=True)


# ------------------------------------------------------------------ filters
US_STATES = ("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ "
             "NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC").split()
US_WORDS = ["united states", "usa", "u.s.", "us-remote", "remote - us", "remote, us", "(us)",
            "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut",
            "delaware", "florida", "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas",
            "kentucky", "louisiana", "maine", "maryland", "massachusetts", "michigan", "minnesota",
            "mississippi", "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey",
            "new mexico", "new york", "north carolina", "north dakota", "ohio", "oklahoma", "oregon",
            "pennsylvania", "rhode island", "south carolina", "south dakota", "tennessee", "texas", "utah",
            "vermont", "virginia", "washington", "west virginia", "wisconsin", "wyoming",
            "san francisco", "seattle", "austin", "boston", "chicago", "los angeles", "denver", "atlanta",
            "phoenix", "tempe", "scottsdale", "san jose", "palo alto", "mountain view", "sunnyvale",
            "san diego", "miami", "dallas", "houston", "pittsburgh", "portland", "detroit", "nyc"]
NON_US = ["canada", "toronto", "vancouver", "montreal", "london", "united kingdom", "uk", "ireland",
          "dublin", "germany", "berlin", "munich", "france", "paris", "india", "bangalore", "bengaluru",
          "hyderabad", "singapore", "japan", "tokyo", "australia", "sydney", "brazil", "mexico", "poland",
          "warsaw", "netherlands", "amsterdam", "spain", "israel", "tel aviv", "china", "vietnam",
          "korea", "seoul", "philippines", "romania", "serbia", "portugal", "lisbon", "sweden", "uae",
          "pune", "chennai", "gurgaon", "gurugram", "noida", "mumbai", "delhi", "emea", "apac", "latam",
          "europe", "asia", "zurich", "switzerland", "italy", "milan", "madrid", "barcelona", "stockholm",
          "copenhagen", "denmark", "finland", "norway", "austria", "belgium", "prague", "czech",
          "hungary", "turkey", "egypt", "nigeria", "kenya", "south africa", "argentina", "chile",
          "colombia", "costa rica", "taiwan", "hong kong", "shanghai", "beijing", "malaysia",
          "indonesia", "thailand", "new zealand", "melbourne", "ontario", "quebec", "british columbia",
          "calgary", "ottawa", "waterloo", "edinburgh", "manchester", "dubai", "ukraine", "estonia",
          "lithuania", "latvia", "greece", "luxembourg"]
US_ABBR = re.compile(r"\b(sf|nyc|bay area|silicon valley|washington dc|d\.c\.)\b", re.I)


def _foreign_code(part):
    bits = [b.strip() for b in re.sub(r"\(.*?\)", "", part).split(",") if b.strip()]
    return len(bits) >= 3 and re.fullmatch(r"[A-Za-z]{2}", bits[-1]) and bits[-1].upper() != "US"


def _part_status(part):
    l = part.lower()
    if _foreign_code(part):
        return "non_us"
    if US_ABBR.search(part):
        return "us"
    if any(re.search(r"\b%s\b" % re.escape(w), l) for w in NON_US):
        return "non_us"
    if (re.search(r",\s*(%s)\b" % "|".join(US_STATES), part) or any(w in l for w in US_WORDS)
            or re.search(r"\bus\b", l)):
        return "us"
    return "unclear"


def location_status(loc):
    """us if ANY listed location is in the US; non_us only if all are clearly abroad."""
    parts = [p for p in re.split(r"[;|/]| or ", loc or "") if p.strip()] or [""]
    st = [_part_status(p) for p in parts]
    if "us" in st:
        return "us"
    if all(s == "non_us" for s in st):
        return "non_us"
    return "unclear"


SENIOR = re.compile(r"\b(senior|sr\.?|staff|principal|lead|manager|director|head of|vp|vice president|"
                    r"chief|distinguished|architect|iii|iv)\b", re.I)
LEVEL_2PLUS = re.compile(r"\b(engineer|developer|analyst|scientist|programmer)\s*(ii|iii|iv|2|3|4)\b(?!\s*/)", re.I)
INTERN = re.compile(r"\b(intern|internship|co-?op)\b", re.I)
EARLY = re.compile(r"\b(new grad|new graduate|university grad|graduate|entry[- ]level|early career|"
                   r"junior|associate|engineer i|apprentice|campus|university)\b|\b(i|1)$", re.I)
YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:-\s*\d{1,2}\s*)?(?:years?|yrs?)\b(?![^.\n]{0,40}\b(?:preferred|"
                   r"nice to have|a plus|bonus)\b)", re.I)
VISA_RISK = re.compile(r"(u\.?s\.? citizen|citizenship (is )?required|security clearance|active clearance|"
                       r"clearance eligib|itar|export control|export-controlled|without (the need for )?"
                       r"(visa )?sponsorship|will not (provide )?sponsor|unable to sponsor|not able to sponsor|"
                       r"no (visa )?sponsorship|permanent resident)", re.I)
CLEARANCE_TITLE = re.compile(r"\b(clearance|cleared|ts/sci|top secret|polygraph)\b", re.I)

ROLE_SYNONYMS = {
    "software engineer": ["software developer", "software development", "sde", "swe", "software dev",
                          "backend", "frontend", "full stack", "fullstack", "mobile engineer"],
    "data analyst": ["data analytics", "data analysis", "business analyst", "analytics"],
    "data engineer": ["data engineering", "data platform", "analytics engineer"],
    "data scientist": ["data science", "machine learning", "applied scientist"],
    "machine learning": ["ml engineer", "ai engineer", "machine learning", "deep learning", "ai/ml"],
    "ai engineer": ["ml engineer", "machine learning", "ai/ml", "applied ai"],
    "product manager": ["product management", "apm", "associate product manager"],
    "backend": ["back end"],
    "full stack": ["fullstack"],
    "designer": ["product design", "ux", "ui/ux"],
}


def _norm_title(t):
    return " " + re.sub(r"[^a-z0-9&+#/]+", " ", t.lower()) + " "


def role_match(role, title):
    t = _norm_title(title)
    r = " ".join(_norm_title(role).split())
    ws = [w for w in r.split() if w not in ("and", "of", "the", "&", "intern", "internship")]
    if ws and all(w in t for w in ws):
        return True
    return any(re.search(r"\b%s\b" % re.escape(s), t) for s in ROLE_SYNONYMS.get(r, []))


def required_years(desc):
    nums = [int(m.group(1)) for m in YEARS.finditer(desc or "") if int(m.group(1)) <= 25]
    return min(nums) if nums else None


def words(s):
    return set(re.findall(r"[a-z][a-z+#.]{1,}", (s or "").lower()))


STOP = words("the and for with you our are will this that from have your team work who what about "
             "able must more into their they other also can all any not but how per such using")


def title_filter(job, p):
    """Cheap filter on title + location only. Returns reason string or None if kept."""
    t = job["title"]
    roles = p.get("roles") or []
    if roles and not any(role_match(r, t) for r in roles):
        return "not your role"
    is_intern = bool(INTERN.search(t))
    level = p.get("level", "both")
    if level == "intern" and not is_intern:
        return "not an internship"
    if level == "newgrad" and is_intern:
        return "internship"
    if level in ("intern", "newgrad", "both") and (SENIOR.search(t) or LEVEL_2PLUS.search(t)):
        return "too senior"
    if p.get("us_only", True) and location_status(job["location"]) == "non_us":
        return "outside US"
    if p.get("sponsorship") and CLEARANCE_TITLE.search(t):
        return "needs clearance"
    if p.get("days") and job.get("posted"):
        if parse_date(job["posted"]) < NOW() - dt.timedelta(days=p["days"]):
            return "too old"
    return None


def full_filter_and_score(job, p, resume_text=""):
    """Second pass once a description is known. Returns (reason or None, job)."""
    is_intern = bool(INTERN.search(job["title"]))
    yrs = required_years(job.get("description"))
    if not is_intern and p.get("level") in ("newgrad", "both") and yrs is not None and yrs > p.get("max_years", 2):
        return "needs more experience", job
    risk = bool(VISA_RISK.search(job.get("description") or ""))
    if p.get("sponsorship") and risk and p.get("hide_visa_risk", True):
        return "no sponsorship / citizenship required", job
    j = dict(job)
    j["is_intern"] = is_intern
    j["visa_flag"] = risk if p.get("sponsorship") else False
    j["years"] = yrs
    loc = location_status(j["location"])
    roles = p.get("roles") or []
    score = sum(50 for r in roles if role_match(r, j["title"]))
    if resume_text:
        score += min(len((words(resume_text) - STOP) & (words(j.get("description")) - STOP)), 60)
    if EARLY.search(j["title"]) or is_intern:
        score += 20
    if loc == "unclear":
        score -= 25
    d = parse_date(j.get("posted"))
    if d:
        days = (NOW() - d).total_seconds() / 86400
        score += max(0, 30 - days)          # fresher first
    j["score"] = round(score, 1)
    return None, j


# ------------------------------------------------------------------ state
def data_path(name):
    return os.path.join(DATA_DIR, name)


def load_json(name, default):
    try:
        with open(data_path(name)) as f:
            return json.load(f)
    except Exception:
        return default


def save_json(name, obj):
    tmp = data_path(name + ".tmp")
    with open(tmp, "w") as f:
        json.dump(obj, f)
    os.replace(tmp, data_path(name))


def public(job, n=None, desc_chars=0):
    """Compact view for printing to Cubbie."""
    out = {"n": n, "title": job["title"], "company": job["company"],
           "location": loc_short(job["location"]), "posted": age_text(parse_date(job.get("posted"))),
           "url": job["url"]}
    if job.get("visa_flag"):
        out["warning"] = "description mentions citizenship/clearance/no sponsorship"
    if desc_chars:
        out["description"] = (job.get("description") or "")[:desc_chars]
    return {k: v for k, v in out.items() if v is not None}


def loc_short(loc, k=2):
    parts = [p.strip() for p in re.split(r"[;|]", loc or "") if p.strip()]
    if len(parts) <= k:
        return "; ".join(parts) or "location not listed"
    return "; ".join(parts[:k]) + f" +{len(parts) - k} more"
