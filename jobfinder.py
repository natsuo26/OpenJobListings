"""Open Job Listings - a small local job search tool.

Run:  python jobfinder.py
Then a browser tab opens at http://localhost:8765

Uses only the Python standard library. Sources (all free, no sign-up):
  * LinkedIn public job search (any country)
  * Workable job search (any country)
  * Impactpool (NGO / UN / development jobs, any country)
  * NHS Jobs (UK only)
  * Bundesagentur fuer Arbeit (Germany only, uses German search phrases
    from categories.json)
  * Remotive and Jobicy (remote jobs open to your country)

Language, job type and experience are worked out from each job's description and
cached in details_cache.json so repeat searches are fast.
"""

import html
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
PORT = 8765
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)

# Titles containing these words are hidden when "Hide senior roles" is on.
SENIOR_WORDS = re.compile(
    r"\b(senior|sr\.?|lead|principal|director|head of|vice president|vp|chief|"
    r"partner|professor|associate professor|staff|chefarzt|"
    r"(?:team|abteilungs|bereichs|sachgebiets|gruppen|standort|einrichtungs|fach|stations|praxis|projekt)?leit(?:ung|er|erin))\b",
    re.I,
)


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def clean(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def block_text(text):
    """Like clean(), but keeps list items and paragraphs on separate lines."""
    text = re.sub(r"(?i)</(li|p|div|h\d|tr|ul|ol)>|<br\s*/?>", "\n", text or "")
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    return "\n".join(line for line in (re.sub(r"\s+", " ", ln).strip() for ln in text.split("\n")) if line)


# ---------------------------------------------------------------- LinkedIn

LI_SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
_li_lock = threading.Semaphore(3)  # be polite: at most 3 LinkedIn requests at once


def linkedin_search(keyword, location, days, pages, entry_only, jobtype=""):
    params = {
        "keywords": keyword,
        "location": location,
        "f_TPR": f"r{int(days) * 86400}",
        "sortBy": "DD",
    }
    if entry_only:
        params["f_E"] = "1,2,3"  # internship, entry level, associate
    if jobtype in ("part", "full"):
        params["f_JT"] = "P" if jobtype == "part" else "F"
    jobs, errors = [], []
    for page in range(pages):
        params["start"] = page * 10
        url = LI_SEARCH + "?" + urllib.parse.urlencode(params)
        body = None
        for attempt in range(3):
            try:
                with _li_lock:
                    body = fetch(url)
                break
            except urllib.error.HTTPError as e:
                if e.code == 400:  # no more pages
                    body = ""
                    break
                if e.code == 429 and attempt < 2:
                    time.sleep(2 + attempt * 3)
                    continue
                errors.append(f"LinkedIn HTTP {e.code}")
                break
            except Exception as e:  # network trouble
                errors.append(f"LinkedIn: {e}")
                break
        if not body:
            break
        found = parse_linkedin(body)
        jobs.extend(found)
        if len(found) < 10:
            break
    return jobs, errors


def parse_linkedin(body):
    jobs = []
    for card in body.split("<li>")[1:]:
        m_id = re.search(r"jobPosting:(\d+)", card)
        m_title = re.search(r'base-search-card__title">(.*?)</h3>', card, re.S)
        if not (m_id and m_title):
            continue
        m_company = re.search(r'base-search-card__subtitle">(.*?)</h4>', card, re.S)
        m_loc = re.search(r'job-search-card__location">(.*?)</span>', card, re.S)
        m_date = re.search(r'<time[^>]*datetime="([^"]+)"', card)
        jobs.append(
            {
                "id": "li-" + m_id.group(1),
                "title": clean(m_title.group(1)),
                "company": clean(m_company.group(1)) if m_company else "",
                "location": clean(m_loc.group(1)) if m_loc else "",
                "posted": m_date.group(1) if m_date else "",
                "url": f"https://www.linkedin.com/jobs/view/{m_id.group(1)}",
                "source": "LinkedIn",
            }
        )
    return jobs


# ---------------------------------------------------------------- languages

# Canonical language name -> regex of ways it is written (English + local names).
LANGUAGES = {
    "English": r"english|englisch\w*|anglais|ingl[eé]s|inglese|engels|engelsk|angielski",
    "German": r"german|deutsch(?!land)\w*|allemand|alem[aá]n|tedesco|duits",
    "French": r"french|französisch\w*|fran[cç]ais[e]?|franc[eé]s|francese|frans",
    "Spanish": r"spanish|spanisch\w*|espa[nñ]ol|espagnol|spagnolo|spaans",
    "Portuguese": r"portuguese|portugiesisch\w*|portugu[eê]s|portoghese",
    "Italian": r"italian|italienisch\w*|italiano|italien",
    "Dutch": r"dutch|niederländisch\w*|nederlands|néerlandais|flemish|vlaams",
    "Arabic": r"arabic|arabisch\w*|arabe|árabe|عربي|العربية",
    "Hindi": r"hindi",
    "Urdu": r"urdu",
    "Bengali": r"bengali|bangla",
    "Tamil": r"tamil",
    "Telugu": r"telugu",
    "Kannada": r"kannada",
    "Malayalam": r"malayalam",
    "Marathi": r"marathi",
    "Gujarati": r"gujarati",
    "Punjabi": r"punjabi",
    "Odia": r"odia|oriya",
    "Mandarin / Chinese": r"mandarin|chinese|chinesisch\w*|putonghua",
    "Cantonese": r"cantonese",
    "Japanese": r"japanese|japanisch\w*",
    "Korean": r"korean",
    "Russian": r"russian|russisch\w*",
    "Ukrainian": r"ukrainian",
    "Polish": r"polish|polnisch\w*|polski",
    "Turkish": r"turkish|türkisch\w*",
    "Greek": r"greek",
    "Hebrew": r"hebrew",
    "Persian / Farsi": r"farsi|persian|dari",
    "Swedish": r"swedish|svenska",
    "Norwegian": r"norwegian|norsk",
    "Danish": r"danish|dansk",
    "Finnish": r"finnish|suomi",
    "Swahili": r"swahili|kiswahili",
    "Amharic": r"amharic",
    "Malay": r"malay|bahasa melayu",
    "Indonesian": r"indonesian|bahasa indonesia",
    "Tagalog / Filipino": r"tagalog|filipino",
    "Thai": r"\bthai\b",
    "Vietnamese": r"vietnamese",
    "Sinhala": r"sinhala|sinhalese",
    "Nepali": r"nepali",
    "Sign language": r"sign language|\bbsl\b|\basl\b|\bisl\b|gebärdensprache",
}
LANG_RE = {k: re.compile(r"(?<!\w)(?:" + v + r")(?!\w)", re.I) for k, v in LANGUAGES.items()}

# A language name only counts if its sentence talks about language ability.
LANG_CUE = re.compile(
    r"fluen|proficien|speak|spoken|written|verbal|native|bilingual|multilingual|language|"
    r"command of|knowledge of|mother tongue|communicat|"
    r"sprach|kenntnis|fließend|verhandlungssicher|muttersprach|"
    r"langue|maîtrise|courant|idioma|dominio|lingua|taal",
    re.I,
)

# ...and is only "nice to have" if the sentence says so.
LANG_OPTIONAL = re.compile(
    r"\bplus\b|advantage|preferred|preferable|desirable|beneficial|bonus|nice to have|"
    r"not essential|not required|would be useful|an asset|"
    r"vorteil|wünschenswert|erwünscht|atout|souhait|valorar|deseable",
    re.I,
)

# Common words used to guess which language an ad is written in.
STOPWORDS = {
    "English": "the and of to with for you we are is our will in this",
    "German": "und der die das mit für wir sie ist ein eine zu bei auf ihre",
    "French": "le les et des pour avec vous nous est une du dans sur votre",
    "Spanish": "el los las y para con una que del por nuestro tu se como",
    "Portuguese": "os e para com uma que não você em do da nosso são",
    "Dutch": "het een en van voor met wij je ons zijn bij naar",
    "Italian": "il di e per con che una del della sono nostro gli",
}
STOPWORDS = {k: set(v.split()) for k, v in STOPWORDS.items()}
SCRIPTS = {
    "Arabic": r"[؀-ۿ]", "Hindi": r"[ऀ-ॿ]", "Mandarin / Chinese": r"[一-鿿]",
    "Japanese": r"[぀-ヿ]", "Korean": r"[가-힯]", "Thai": r"[฀-๿]",
    "Russian": r"[Ѐ-ӿ]", "Greek": r"[Ͱ-Ͽ]", "Hebrew": r"[֐-׿]",
}


def posting_language(text):
    letters = len(re.findall(r"\w", text)) or 1
    for lang, pat in SCRIPTS.items():
        if len(re.findall(pat, text)) / letters > 0.3:
            return lang
    words = re.findall(r"[a-zà-ÿ]+", text.lower())
    if len(words) < 15:
        return ""
    scores = {k: sum(w in sw for w in words) for k, sw in STOPWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] >= 5 else ""


def detect_languages(title, description):
    """Languages a job needs (the ad's own language plus any it asks for),
    and languages it only lists as a bonus."""
    posting = posting_language(description)
    needed = {posting} if posting else set()
    bonus = set()
    for sentence in re.split(r"[.;:!?•\n\r]+|\s[-–]\s", title + ".\n" + description):
        if LANG_CUE.search(sentence):
            found = {k for k, rx in LANG_RE.items() if rx.search(sentence)}
            (bonus if LANG_OPTIONAL.search(sentence) else needed).update(found)
    return {"langs": sorted(needed), "bonus": sorted(bonus - needed), "posting": posting}


# ---------------------------------------------------------------- job type & experience

JOB_TYPES = ["Full-time", "Part-time", "Contract", "Temporary", "Internship", "Volunteer"]
TYPE_TEXT = {
    "Part-time": r"part[- ]?time|teilzeit|mi-temps|temps partiel|tiempo parcial|media jornada",
    "Full-time": r"full[- ]?time|vollzeit|temps plein|tiempo completo|jornada completa",
    "Internship": r"\bintern(ship)?\b|praktik|werkstudent|stagiaire|\bstage\b|pasant[ií]a",
    "Contract": r"\bcontract\b|freelance|consultan(t|cy)|befristet|\bcdd\b",
    "Temporary": r"\btemporary\b|\btemp\b|fixed[- ]term|maternity cover|locum|\bbank\b",
    "Volunteer": r"volunteer|ehrenamt|bénévol|voluntari",
}
TYPE_RE = {k: re.compile(v, re.I) for k, v in TYPE_TEXT.items()}
# "26 hours per week", "20 Stunden/Woche" - counted as part-time only when 30 hours or fewer.
WEEKLY_HOURS = re.compile(
    r"(?<![\d.])(\d{1,2}(?:\.\d)?)\s*(?:hours|hrs|stunden|std\.?)\s*(?:per|a|each|/|pro|in der)\s*(?:week|wk|woche)", re.I
)


def normalise_type(value):
    v = (value or "").lower().replace("_", "-").replace(" ", "-")
    for t in JOB_TYPES:
        if t.lower() in v:
            return t
    return {"freelance": "Contract", "internship": "Internship", "intern": "Internship"}.get(v, "")


def detect_job_types(title, text, known=()):
    """Job types from the source's own label(s) plus clear wording in the title or ad."""
    types = {t for t in (normalise_type(k) for k in known) if t}
    for t in ("Part-time", "Internship", "Volunteer"):
        if TYPE_RE[t].search(title):
            types.add(t)
    # In the ad body, only trust part-time wording (e.g. "this is a part-time role", "20 hours per week").
    if TYPE_RE["Part-time"].search(text or ""):
        types.add("Part-time")
    if any(float(h) <= 30 for h in WEEKLY_HOURS.findall(text or "")):
        types.add("Part-time")
    return sorted(types, key=JOB_TYPES.index)


# Phrases meaning no experience is needed.
NO_EXP = re.compile(
    r"no (?:prior |previous |professional |work |relevant |formal )?experience (?:is )?(?:required|necessary|needed)|"
    r"no experience\b|without (?:prior |previous )?experience|experience (?:is )?not (?:required|necessary|needed)|"
    r"\bfreshers?\b|fresh graduates?|\b0\s*(?:-|–|to)\s*[12]\s*(?:years?|yrs?)|\b0\+?\s*(?:years?|yrs?)|"
    r"keine (?:berufs)?erfahrung (?:erforderlich|notwendig|nötig|vorausgesetzt)|ohne (?:berufs)?erfahrung|"
    r"quereinsteiger|quereinstieg|sans expérience|aucune expérience|sin experiencia",
    re.I,
)
NO_EXP_TITLE = re.compile(
    r"\bintern(ship)?\b|\btrainee\b|apprentice|graduate (?:programme|program|scheme)|"
    r"praktik|werkstudent|auszubildend|ausbildung|\bazubi\b|\bfsj\b|bundesfreiwillig|stagiaire|volunteer",
    re.I,
)
ENTRY = re.compile(
    r"entry[- ]level|\bjunior\b|recent graduates?|new graduates?|graduates? (?:are )?welcome|early[- ]career|"
    r"berufseinsteiger|berufsanfänger|absolvent|débutant|recién titulado",
    re.I,
)
YEARS = re.compile(
    r"(?:minimum (?:of )?|at least |min\.? )?(\d{1,2})\s*(?:\+|plus)?\s*(?:(?:-|–|to)\s*\d{1,2}\s*\+?\s*)?"
    r"(?:years?|yrs?|jahre?n?|ans|años)\b[^.\n]{0,60}?(?:experience|erfahrung|expérience|experiencia)|"
    r"(?:experience|erfahrung)[^.\n]{0,30}?(?:of |von )?(?:minimum |at least |mindestens )?(\d{1,2})\s*\+?\s*(?:years?|yrs?|jahre?n?)",
    re.I,
)


def detect_experience(title, text, seniority=""):
    """How much experience a job asks for:
    'none' (no experience needed), 'entry' (0-1 years / entry level), 'mid' (2 years),
    'experienced' (3+ years) or '' (not stated)."""
    text = text or ""
    nums = [int(a or b) for a, b in YEARS.findall(text) if int(a or b) <= 20]
    years = min(nums) if nums else None
    seniority = (seniority or "").lower()
    if NO_EXP_TITLE.search(title) or "internship" in seniority:
        level = "none"
    elif NO_EXP.search(title + "\n" + text) and (years is None or years <= 1):
        level = "none"
    elif years is not None:
        level = "none" if years == 0 else "entry" if years == 1 else "mid" if years == 2 else "experienced"
    elif ENTRY.search(title + "\n" + text) or "entry" in seniority:
        level = "entry"
    else:
        level = ""
    return {"exp": level, "years": years}


def analyze(title, text, known_types=(), seniority=""):
    """Everything the page shows about a job: languages, job type and experience."""
    return {
        **detect_languages(title, text),
        "types": detect_job_types(title, text, known_types),
        **detect_experience(title, text, seniority),
    }


LI_JOB = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/"
CACHE_FILE = HERE / "details_cache.json"
_cache_lock = threading.Lock()
try:
    _lang_cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
except Exception:
    _lang_cache = {}


IP_JOB = "https://www.impactpool.org/jobs/"
_ip_lock = threading.Semaphore(3)


def job_details(job_id, title, hint=""):
    """Fetch a LinkedIn or Impactpool ad and work out its languages, type and experience (cached)."""
    if job_id in _lang_cache:
        return _lang_cache[job_id]
    prefix, num = job_id.split("-", 1)
    url, lock, name = (LI_JOB + num, _li_lock, "LinkedIn") if prefix == "li" else (IP_JOB + num, _ip_lock, "Impactpool")
    for attempt in range(3):
        try:
            with lock:
                page = fetch(url)
            break
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 2:
                time.sleep(2 + attempt * 3)
                continue
            return {"error": f"{name} HTTP {e.code}"}
        except Exception as e:
            return {"error": str(e)}
    if prefix == "li":
        m = re.search(r"show-more-less-html__markup[^>]*>(.*?)</div>", page, re.S)
        text = block_text(m.group(1)) if m else ""
        criteria = dict(
            (clean(k), clean(v)) for k, v in
            re.findall(r'job-criteria-subheader">(.*?)</h3>\s*<span[^>]*>(.*?)</span>', page, re.S)
        )
        result = analyze(title, text, [criteria.get("Employment type", "")], criteria.get("Seniority level", ""))
    else:
        m = re.search(r"<main.*?</main>", page, re.S)
        text = block_text(m.group(0)) if m else ""
        # Impactpool adds a "Speaks X, Y, Z" summary that lumps optional languages in with required ones.
        text = re.sub(r"\bSpeaks (?:[A-Z][a-z]+(?:, | and |\b))+", "", text)
        # hint = the card's contract/level line, e.g. "Internship" or "Junior level"
        result = analyze(title, text, [hint], hint)
    with _cache_lock:
        _lang_cache[job_id] = result
    return result


def details_for(qs):
    jobs = json.loads(qs.get("jobs", ["[]"])[0])  # [[id, title, hint], ...]
    out = {}
    for job_id, title, *rest in jobs[:10]:
        if job_id.startswith(("li-", "ip-")):
            out[job_id] = job_details(job_id, title, rest[0] if rest else "")
    with _cache_lock:
        try:
            CACHE_FILE.write_text(json.dumps(_lang_cache), encoding="utf-8")
        except OSError:
            pass
    return out


# ---------------------------------------------------------------- Remotive

_remotive_cache = {"at": 0, "jobs": []}
_remotive_lock = threading.Lock()


def remotive_all():
    # Remotive asks callers not to hit the API often, so cache for 6 hours.
    with _remotive_lock:
        if time.time() - _remotive_cache["at"] > 6 * 3600:
            data = json.loads(fetch("https://remotive.com/api/remote-jobs", timeout=40))
            _remotive_cache["jobs"] = data.get("jobs", [])
            _remotive_cache["at"] = time.time()
        return _remotive_cache["jobs"]


def remotive_search(keyword, country, days):
    try:
        all_jobs = remotive_all()
    except Exception as e:
        return [], [f"Remotive: {e}"]
    words = [w.lower() for w in re.findall(r"\w+", keyword) if len(w) > 2]
    cutoff = cutoff_date(days)
    out = []
    for j in all_jobs:
        posted = (j.get("publication_date") or "")[:10]
        if posted and posted < cutoff:
            continue
        if not open_to(j.get("candidate_required_location"), country):
            continue
        hay = (j.get("title", "") + " " + j.get("category", "")).lower()
        if not all(w in hay for w in words):
            continue
        out.append(
            {
                "id": f"rm-{j.get('id')}",
                "title": clean(j.get("title")),
                "company": clean(j.get("company_name")),
                "location": "Remote - " + (j.get("candidate_required_location") or "Anywhere"),
                "posted": posted,
                "url": j.get("url", ""),
                "source": "Remotive",
                **analyze(j.get("title", ""), block_text(j.get("description")), [j.get("job_type")]),
            }
        )
    return out, []


# ---------------------------------------------------------------- country helpers

UK_NAMES = {"uk", "u.k.", "united kingdom", "great britain", "britain", "england", "scotland", "wales", "northern ireland"}
DE_NAMES = {"germany", "deutschland"}
COUNTRY_ALIASES = {
    "uk": "United Kingdom", "great britain": "United Kingdom", "britain": "United Kingdom", "england": "United Kingdom",
    "us": "United States", "usa": "United States", "america": "United States",
    "uae": "United Arab Emirates", "ksa": "Saudi Arabia",
    "south korea": "Korea (the Republic of)", "korea": "Korea (the Republic of)",
    "north korea": "Korea (the Democratic People's Republic of)",
    "russia": "Russian Federation", "czechia": "Czech Republic", "laos": "Lao",
    "drc": "Congo Democratic", "dr congo": "Congo Democratic", "türkiye": "Turkey", "turkiye": "Turkey",
    "viet nam": "Vietnam",
}


def country_terms(country):
    """Different ways a country may be written in a job's location text."""
    c = country.strip().lower()
    terms = {c, COUNTRY_ALIASES.get(c, c).lower()}
    if c in UK_NAMES or "kingdom" in c:
        terms |= {"uk", "united kingdom", "britain", "england"}
    if c in ("us", "usa", "united states", "united states of america", "america"):
        terms |= {"usa", "us", "united states", "america"}
    if c in ("uae", "united arab emirates"):
        terms |= {"uae", "united arab emirates"}
    return terms


def open_to(where, country):
    """True if a remote job's allowed-locations text includes this country (or anywhere)."""
    where = (where or "").lower()
    if not where or any(x in where for x in ("worldwide", "anywhere", "global")):
        return True
    return any(re.search(r"(?<![a-z])" + re.escape(t) + r"(?![a-z])", where) for t in country_terms(country))


def cutoff_date(days):
    return time.strftime("%Y-%m-%d", time.gmtime(time.time() - int(days) * 86400))


def keyword_words(keyword):
    """Word stems used to check a result is on-topic ("psychology" -> "psycho" also matches "psychologist")."""
    return [w.lower()[:6] for w in re.findall(r"\w+", keyword) if len(w) > 3]


def on_topic(keyword, text):
    words = keyword_words(keyword)
    text = text.lower()
    return not words or any(w in text for w in words)


# ---------------------------------------------------------------- Jobicy (remote)

_jobicy_cache = {"at": 0, "jobs": []}
_jobicy_lock = threading.Lock()


def jobicy_search(keyword, country, days):
    try:
        with _jobicy_lock:  # Jobicy asks for infrequent polling, so cache for 6 hours
            if time.time() - _jobicy_cache["at"] > 6 * 3600:
                data = json.loads(fetch("https://jobicy.com/api/v2/remote-jobs?count=100", timeout=40))
                _jobicy_cache.update(jobs=data.get("jobs", []), at=time.time())
            all_jobs = _jobicy_cache["jobs"]
    except Exception as e:
        return [], [f"Jobicy: {e}"]
    words = [w.lower() for w in re.findall(r"\w+", keyword) if len(w) > 2]
    cutoff = cutoff_date(days)
    out = []
    for j in all_jobs:
        posted = (j.get("pubDate") or "")[:10]
        if posted and posted < cutoff:
            continue
        if not open_to(j.get("jobGeo"), country):
            continue
        hay = (j.get("jobTitle", "") + " " + " ".join(j.get("jobIndustry") or [])).lower()
        if not all(w in hay for w in words):
            continue
        out.append({
            "id": f"jc-{j.get('id')}",
            "title": clean(j.get("jobTitle")),
            "company": clean(j.get("companyName")),
            "location": "Remote - " + (clean(j.get("jobGeo")) or "Anywhere"),
            "posted": posted,
            "url": j.get("url", ""),
            "source": "Jobicy",
            **analyze(j.get("jobTitle", ""), block_text(j.get("jobDescription")), j.get("jobType") or [],
                      " ".join(j.get("jobLevel") or []) if isinstance(j.get("jobLevel"), list) else j.get("jobLevel") or ""),
        })
    return out, []


# ---------------------------------------------------------------- Workable (any country)

def workable_search(keyword, country, city, days, pages):
    cutoff = cutoff_date(days)
    params = {"query": keyword, "location": country}
    out = []
    for _ in range(pages):
        try:
            data = json.loads(fetch("https://jobs.workable.com/api/v1/jobs?" + urllib.parse.urlencode(params)))
        except Exception as e:
            return out, [f"Workable: {e}"]
        for j in data.get("jobs", []):
            posted = (j.get("created") or "")[:10]
            if posted and posted < cutoff:
                continue
            where = ", ".join(j.get("locations") or [])
            if city and city.lower() not in where.lower():
                continue
            # Workable matches words anywhere in the ad, so keep only jobs where they matter.
            if not on_topic(keyword, " ".join([j.get("title") or "", j.get("department") or "",
                                               clean(j.get("requirementsSection"))])):
                continue
            text = block_text((j.get("description") or "") + "\n" + (j.get("requirementsSection") or ""))
            out.append({
                "id": f"wk-{j.get('id')}",
                "title": clean(j.get("title")),
                "company": clean((j.get("company") or {}).get("title")),
                "location": where + (" (remote)" if j.get("workplace") == "remote" else ""),
                "posted": posted,
                "url": j.get("url", ""),
                "source": "Workable",
                **analyze(j.get("title", ""), text, [j.get("employmentType")]),
            })
        token = data.get("nextPageToken")
        if not token or not data.get("jobs"):
            break
        params["pageToken"] = token
    return out, []


# ---------------------------------------------------------------- Impactpool (NGO / UN, any country)

_ip_countries = {}


def impactpool_country_id(country):
    if not _ip_countries:
        page = fetch("https://www.impactpool.org/search")
        m = re.search(r"data-options='([^']*)'[^>]*id='search-filter-wl'", page)
        for o in json.loads(html.unescape(m.group(1))):
            _ip_countries[o["name"].lower()] = o["id"]
    terms = [t for t in (country.lower(), COUNTRY_ALIASES.get(country.lower(), "").lower()) if t]
    for term in terms:
        if term in _ip_countries:
            return _ip_countries[term]
    # e.g. "united kingdom" -> "united kingdom of great britain..." (skip short terms: "uk" is not "ukraine")
    for term in terms:
        for name, cid in _ip_countries.items():
            if len(term) >= 4 and name.startswith(term):
                return cid
    return None


def impactpool_search(keyword, country, pages):
    try:
        cid = impactpool_country_id(country)
    except Exception as e:
        return [], [f"Impactpool: {e}"]
    if cid is None:
        return [], [f"Impactpool doesn't list a country called '{country}'"]
    out = []
    for page_no in range(1, min(pages, 3) + 1):
        url = "https://www.impactpool.org/search?" + urllib.parse.urlencode({"q": keyword, "wl[]": cid, "page": page_no})
        try:
            with _ip_lock:
                body = fetch(url)
        except Exception as e:
            return out, [f"Impactpool: {e}"]
        cards = body.split("<div class='job'>")[1:]
        for card in cards:
            m_id = re.search(r'href="/jobs/(\d+)"', card)
            m_title = re.search(r"type='cardTitle'>(.*?)</h3>", card, re.S)
            if not (m_id and m_title):
                continue
            m_org = re.search(r"color: #1C1B16;' type='bodyEmphasis'>(.*?)<img", card, re.S)
            m_loc = re.search(r"color: #63625B;' type='bodyEmphasis'>(.*?)</div>", card, re.S)
            m_level = re.search(r"color: #75736C;' type='bodyEmphasis'>(.*?)</div>", card, re.S)
            out.append({
                "id": "ip-" + m_id.group(1),
                "title": clean(m_title.group(1)),
                "company": clean(m_org.group(1)) if m_org else "",
                "location": clean(m_loc.group(1)) if m_loc else "",
                "posted": "",  # Impactpool doesn't show a posting date
                "url": IP_JOB + m_id.group(1),
                "source": "Impactpool",
                "hint": clean(m_level.group(1)) if m_level else "",  # e.g. "Internship" or "Junior level"
            })
        if len(cards) < 20:
            break
    return out, []


# ---------------------------------------------------------------- NHS Jobs (UK only)

def nhs_search(keyword, city, days, pages, jobtype=""):
    cutoff = cutoff_date(days)
    out = []
    for page_no in range(1, pages + 1):
        params = {"keyword": keyword, "page": page_no}
        if city:
            params["location"] = city
        if jobtype in ("part", "full"):
            params["workingPattern"] = "part-time" if jobtype == "part" else "full-time"
        try:
            body = fetch("https://www.jobs.nhs.uk/api/v1/search_xml?" + urllib.parse.urlencode(params))
        except Exception as e:
            return out, [f"NHS Jobs: {e}"]
        items = re.findall(r"<vacancyDetails>(.*?)</vacancyDetails>", body, re.S)
        for v in items:
            tag = lambda t: clean((re.search(rf"<{t}>(.*?)</{t}>", v, re.S) or [None, ""])[1])
            posted = tag("postDate")[:10]
            if posted and posted < cutoff:
                continue
            known = {"part": ["Part-time"], "full": ["Full-time"]}.get(jobtype, []) + [tag("type")]
            langs = analyze(tag("title"), tag("description"), known)
            if not langs["posting"]:
                langs = {**langs, "posting": "English", "langs": sorted(set(langs["langs"]) | {"English"})}
            out.append({
                "id": "nhs-" + tag("id"),
                "title": tag("title"),
                "company": tag("employer"),
                "location": ", ".join(clean(x) for x in re.findall(r"<location>(.*?)</location>", v)) + ", UK",
                "posted": posted,
                "url": tag("url"),
                "source": "NHS Jobs",
                **langs,
            })
        if len(items) < 10:
            break
    return out, []


# ---------------------------------------------------------------- Bundesagentur für Arbeit (Germany only)

def german_keyword(keyword):
    try:
        data = json.loads((HERE / "categories.json").read_text(encoding="utf-8"))
        return data.get("german_keywords", {}).get(keyword.lower(), keyword)
    except Exception:
        return keyword


def ba_search(keyword, city, days, pages, jobtype=""):
    query = german_keyword(keyword)
    params = {"was": query, "size": min(25 * pages, 100), "page": 1, "veroeffentlichtseit": min(int(days), 100)}
    if city:
        params["wo"] = city
    if jobtype in ("part", "full"):
        params["arbeitszeit"] = "tz" if jobtype == "part" else "vz"
    try:
        data = json.loads(_ba_fetch(params))
    except Exception as e:
        return [], [f"Bundesagentur: {e}"]
    cutoff = cutoff_date(days)
    out = []
    for j in data.get("ergebnisliste", []):
        title = clean(j.get("stellenangebotsTitel"))
        # The agency's search is loose, so keep only jobs that mention a search word.
        if not on_topic(query, title + " " + " ".join(j.get("alleBerufe") or [])):
            continue
        if (j.get("datumErsteVeroeffentlichung") or "9")[:10] < cutoff:
            continue
        addr = ((j.get("stellenlokationen") or [{}])[0]).get("adresse", {})
        english_ad = bool(re.search(r"\(m/f|\(f/m|\b(and|of|the|for|with)\b", title, re.I))
        posting = "English" if english_ad else "German"
        known = []
        if j.get("arbeitszeitVollzeit"):
            known.append("Full-time")
        if any(v for k, v in j.items() if k.startswith("arbeitszeitTeilzeit")):
            known.append("Part-time")
        if j.get("stellenangebotsart") in ("AUSBILDUNG", "PRAKTIKUM_TRAINEE"):
            known.append("Internship")
        info = analyze(title, "", known)
        # "Quereinstieg geeignet" = open to career changers, i.e. no specific experience needed
        if j.get("quereinstiegGeeignet") or "Internship" in known:
            info.update(exp="none")
        out.append({
            "id": "ba-" + j.get("referenznummer", ""),
            "title": title,
            "company": clean(j.get("firma")),
            "location": ", ".join(x for x in [addr.get("ort"), (addr.get("region") or "").replace("_", "-").title(), "Germany"] if x),
            "posted": (j.get("datumErsteVeroeffentlichung") or "")[:10],
            "url": "https://www.arbeitsagentur.de/jobsuche/jobdetail/" + j.get("referenznummer", ""),
            "source": "Bundesagentur",
            **info,
            "langs": [posting], "bonus": [], "posting": posting,
        })
    return out, []


def _ba_fetch(params):
    req = urllib.request.Request(
        "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs?" + urllib.parse.urlencode(params),
        headers={"User-Agent": UA, "X-API-Key": "jobboerse-jobsuche"},  # the agency's published public key
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        return resp.read().decode("utf-8", "replace")


# ---------------------------------------------------------------- server

ALL_SOURCES = {"li", "wk", "ip", "nhs", "ba", "remote"}


def search(qs):
    keyword = qs.get("keyword", [""])[0].strip()
    country = qs.get("country", [""])[0].strip()
    city = qs.get("city", [""])[0].strip()
    days = max(1, min(int(qs.get("days", ["7"])[0] or 7), 90))
    pages = max(1, min(int(qs.get("pages", ["2"])[0] or 2), 10))
    entry_only = qs.get("entry", ["0"])[0] == "1"
    jobtype = qs.get("jobtype", [""])[0]  # "", "part" or "full"
    hide_senior = qs.get("hidesenior", ["1"])[0] == "1"
    sources = set(qs.get("sources", [",".join(ALL_SOURCES)])[0].split(","))
    if not keyword or not country:
        return {"jobs": [], "errors": ["keyword and country are required"]}

    location = f"{city}, {country}" if city else country
    tasks = []
    if "li" in sources:
        tasks.append(lambda: linkedin_search(keyword, location, days, pages, entry_only, jobtype))
    if "wk" in sources:
        tasks.append(lambda: workable_search(keyword, country, city, days, pages))
    if "ip" in sources:
        tasks.append(lambda: impactpool_search(keyword, country, pages))
    if "nhs" in sources and country.lower() in UK_NAMES:
        tasks.append(lambda: nhs_search(keyword, city, days, pages, jobtype))
    if "ba" in sources and country.lower() in DE_NAMES:
        tasks.append(lambda: ba_search(keyword, city, days, pages, jobtype))
    if "remote" in sources:
        tasks.append(lambda: remotive_search(keyword, country, days))
        tasks.append(lambda: jobicy_search(keyword, country, days))

    jobs, errors = [], []
    with ThreadPoolExecutor(max_workers=len(tasks) or 1) as pool:
        for found, errs in pool.map(lambda t: t(), tasks):
            jobs += found
            errors += errs
    if hide_senior:
        jobs = [j for j in jobs if not SENIOR_WORDS.search(j["title"])]
    # Jobs whose type is already known can be filtered now; LinkedIn and Impactpool
    # jobs get their type later, when the page reads each ad.
    if jobtype == "part":
        jobs = [j for j in jobs if "types" not in j or "Part-time" in j["types"]]
    elif jobtype == "full":
        jobs = [j for j in jobs if "Part-time" not in j.get("types", []) or "Full-time" in j["types"]]
    return {"jobs": jobs, "errors": errors}


# ---------------------------------------------------------------- my saved jobs

# Saved / applied / dismissed jobs live in my_jobs.json so they survive new searches,
# restarts and clearing the browser.
MY_JOBS_FILE = HERE / "my_jobs.json"
_my_jobs_lock = threading.Lock()
JOB_FIELDS = ("title", "company", "location", "posted", "url", "source", "langs", "bonus", "posting",
              "types", "exp", "years", "cats")
STATUSES = ("saved", "applied", "hidden")


def load_my_jobs():
    try:
        return json.loads(MY_JOBS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def update_my_job(body):
    """Set a job's status (saved / applied / hidden, or None to forget it) and/or its note."""
    job_id = str(body.get("id", ""))[:100]
    if not job_id:
        raise ValueError("missing job id")
    today = time.strftime("%Y-%m-%d")
    with _my_jobs_lock:
        data = load_my_jobs()
        rec = data.get(job_id, {})
        for k in JOB_FIELDS:  # keep the newest copy of the job's details
            if (body.get("job") or {}).get(k) not in (None, ""):
                rec[k] = body["job"][k]
        if "note" in body:
            rec["note"] = str(body["note"])[:5000]
        if "status" in body:
            status = body["status"]
            if status is None:
                data.pop(job_id, None)
                rec = None
            elif status in STATUSES:
                if status != rec.get("status"):
                    rec["status"] = status
                    rec[f"{status}_on"] = today
                if status != "hidden":
                    rec.setdefault("saved_on", today)
        if rec is not None:
            data[job_id] = rec
        tmp = MY_JOBS_FILE.with_suffix(".tmp")  # write-then-rename so a crash can't corrupt the file
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(MY_JOBS_FILE)
    return {"ok": True, "job": rec}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # keep the console quiet

    def send(self, code, body, ctype):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        try:
            if parsed.path in ("/", "/index.html"):
                self.send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif parsed.path == "/api/categories":
                self.send(200, (HERE / "categories.json").read_bytes(), "application/json")
            elif parsed.path == "/api/search":
                self.send(200, json.dumps(search(qs)), "application/json")
            elif parsed.path in ("/api/details", "/api/languages"):
                self.send(200, json.dumps(details_for(qs)), "application/json")
            elif parsed.path == "/api/myjobs":
                with _my_jobs_lock:
                    self.send(200, json.dumps(load_my_jobs()), "application/json")
            else:
                self.send(404, "Not found", "text/plain")
        except Exception as e:
            self.send(500, json.dumps({"jobs": [], "errors": [str(e)]}), "application/json")

    def do_POST(self):
        if self.path == "/api/shutdown":
            self.send(200, "Job Finder stopped.", "text/plain")
            print("Stopped from the web page.")
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        elif self.path == "/api/myjobs":
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                self.send(200, json.dumps(update_my_job(body)), "application/json")
            except Exception as e:
                self.send(400, json.dumps({"ok": False, "error": str(e)}), "application/json")
        else:
            self.send(404, "Not found", "text/plain")


def main():
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError:
        print(f"Job Finder already seems to be running - opening http://localhost:{PORT}")
        webbrowser.open(f"http://localhost:{PORT}")
        return
    url = f"http://localhost:{PORT}"
    print(f"Job Finder is running at {url}")
    print("Keep this window open while you search.")
    print("To stop: click 'Stop Job Finder' on the page, close this window, or press Ctrl+C.")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
