"""Open Job Listings - a small local job search tool.

Run:  python jobfinder.py
Then a browser tab opens at http://localhost:8765

Uses only the Python standard library. Sources:
  * LinkedIn public job search (works for any country, no login needed)
  * Remotive (remote jobs, filtered to ones open to your country)

Language requirements are worked out from each job's description and
cached in language_cache.json so repeat searches are fast.
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
    r"partner|professor|associate professor|staff)\b",
    re.I,
)


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def clean(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


# ---------------------------------------------------------------- LinkedIn

LI_SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
_li_lock = threading.Semaphore(3)  # be polite: at most 3 LinkedIn requests at once


def linkedin_search(keyword, location, days, pages, entry_only):
    params = {
        "keywords": keyword,
        "location": location,
        "f_TPR": f"r{int(days) * 86400}",
        "sortBy": "DD",
    }
    if entry_only:
        params["f_E"] = "1,2,3"  # internship, entry level, associate
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


LI_JOB = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/"
CACHE_FILE = HERE / "language_cache.json"
_cache_lock = threading.Lock()
try:
    _lang_cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
except Exception:
    _lang_cache = {}


def linkedin_languages(job_id, title):
    if job_id in _lang_cache:
        return _lang_cache[job_id]
    num = job_id.removeprefix("li-")
    for attempt in range(3):
        try:
            with _li_lock:
                page = fetch(LI_JOB + num)
            break
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 2:
                time.sleep(2 + attempt * 3)
                continue
            return {"error": f"LinkedIn HTTP {e.code}"}
        except Exception as e:
            return {"error": str(e)}
    m = re.search(r"show-more-less-html__markup[^>]*>(.*?)</div>", page, re.S)
    result = detect_languages(title, clean(m.group(1)) if m else "")
    with _cache_lock:
        _lang_cache[job_id] = result
    return result


def languages_for(qs):
    jobs = json.loads(qs.get("jobs", ["[]"])[0])  # [[id, title], ...]
    out = {}
    for job_id, title in jobs[:10]:
        if job_id.startswith("li-"):
            out[job_id] = linkedin_languages(job_id, title)
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
    cutoff = time.strftime("%Y-%m-%d", time.gmtime(time.time() - int(days) * 86400))
    country_l = country.lower()
    out = []
    for j in all_jobs:
        posted = (j.get("publication_date") or "")[:10]
        if posted and posted < cutoff:
            continue
        where = (j.get("candidate_required_location") or "").lower()
        if where and not any(x in where for x in (country_l, "worldwide", "anywhere")):
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
                **detect_languages(j.get("title", ""), clean(j.get("description"))),
            }
        )
    return out, []


# ---------------------------------------------------------------- server


def search(qs):
    keyword = qs.get("keyword", [""])[0].strip()
    country = qs.get("country", [""])[0].strip()
    city = qs.get("city", [""])[0].strip()
    days = max(1, min(int(qs.get("days", ["7"])[0] or 7), 90))
    pages = max(1, min(int(qs.get("pages", ["2"])[0] or 2), 10))
    entry_only = qs.get("entry", ["0"])[0] == "1"
    remote = qs.get("remote", ["1"])[0] == "1"
    hide_senior = qs.get("hidesenior", ["1"])[0] == "1"
    if not keyword or not country:
        return {"jobs": [], "errors": ["keyword and country are required"]}

    location = f"{city}, {country}" if city else country
    jobs, errors = linkedin_search(keyword, location, days, pages, entry_only)
    if remote:
        r_jobs, r_err = remotive_search(keyword, country, days)
        jobs += r_jobs
        errors += r_err
    if hide_senior:
        jobs = [j for j in jobs if not SENIOR_WORDS.search(j["title"])]
    return {"jobs": jobs, "errors": errors}


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
            elif parsed.path == "/api/languages":
                self.send(200, json.dumps(languages_for(qs)), "application/json")
            else:
                self.send(404, "Not found", "text/plain")
        except Exception as e:
            self.send(500, json.dumps({"jobs": [], "errors": [str(e)]}), "application/json")

    def do_POST(self):
        if self.path == "/api/shutdown":
            self.send(200, "Job Finder stopped.", "text/plain")
            print("Stopped from the web page.")
            threading.Thread(target=self.server.shutdown, daemon=True).start()
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
