from __future__ import annotations

import argparse
import hashlib
import html
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Callable


SCHEMA_VERSION = "rq4-deterministic-validator-result-v1"
CHROME_PATH = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
CHROME_SHA256 = "e8bce39747ea63c9c7d4306f7635d2916c9ecb0cf913fbcf5e7acc4539b5b8a0"
COASTAL_URL = "https://files.silverpine-media.example/scl/fi/b8r3w6k1m9q4t7v2x5p0/Coastal-Aerial-Narration.mp4?dl=0"
BRAND_TOKENS = {"--ink": "#172033", "--accent": "#3659d9", "--paper": "#f4f7fb"}


class CandidateFailure(RuntimeError):
    pass


class HarnessFault(RuntimeError):
    pass


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise CandidateFailure(message)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_env() -> dict[str, str]:
    keep = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC"}
    env = {key: value for key, value in os.environ.items() if key.upper() in keep}
    env.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0", "NO_PROXY": "*"})
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env.pop(key, None)
    return env


def _run(command: list[str], cwd: Path, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    kwargs: dict[str, Any] = {
        "cwd": cwd, "env": _safe_env(), "text": True,
        "stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "timeout": timeout,
    }
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000
    try:
        return subprocess.run(command, **kwargs)
    except subprocess.TimeoutExpired as exc:
        raise HarnessFault(f"command timed out after {timeout}s: {command[0]}") from exc
    except OSError as exc:
        raise HarnessFault(f"cannot launch {command[0]}: {exc}") from exc


def _repo(path: Path) -> Path:
    path = path.resolve()
    if not path.is_dir() or not (path / "scripts" / "build.py").is_file():
        raise HarnessFault("repository is missing scripts/build.py")
    return path


def _build(repo: Path) -> list[dict[str, Any]]:
    checks = []
    for test_id, script in (("BUILD-001", "build.py"), ("BUILD-002", "check.py")):
        process = _run([sys.executable, str(repo / "scripts" / script)], repo)
        checks.append({"test_id": test_id, "exit_code": process.returncode})
        if process.returncode != 0:
            raise CandidateFailure(f"{script} failed: {(process.stderr or process.stdout)[-1600:]}")
    for name in ("index.html", "catalog.json"):
        artifact = repo / "dist" / name
        if not artifact.is_file() or artifact.stat().st_size == 0:
            raise CandidateFailure(f"missing built artifact dist/{name}")
    return checks


def _regression(repo: Path) -> list[dict[str, Any]]:
    process = _run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], repo)
    if process.returncode != 0:
        raise CandidateFailure(f"repository regression tests failed: {(process.stderr or process.stdout)[-1800:]}")
    return [{"test_id": "REG-001", "exit_code": 0}]


def _app(repo: Path):
    src = str(repo / "src")
    sys.path.insert(0, src)
    try:
        for name in ("application", "domain", "runtime", "current_state"):
            sys.modules.pop(name, None)
        return importlib.import_module("application").create_app()
    except Exception as exc:
        raise CandidateFailure(f"cannot create public application: {exc}") from exc
    finally:
        if sys.path and sys.path[0] == src:
            sys.path.pop(0)


def _catalog(repo: Path) -> dict[str, Any]:
    path = repo / "dist" / "catalog.json"
    if not path.is_file():
        raise CandidateFailure("target test requires built dist/catalog.json")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CandidateFailure(f"catalog.json is unreadable: {exc}") from exc
    if not isinstance(value, dict):
        raise CandidateFailure("catalog.json root must be an object")
    return value


def _feature(catalog: dict[str, Any], slug: str) -> dict[str, Any]:
    for item in catalog.get("features", []):
        if isinstance(item, dict) and item.get("slug") == slug:
            return item
    raise CandidateFailure(f"built catalog omits feature {slug}")


def _built_text(repo: Path) -> str:
    parts = []
    for path in sorted((repo / "dist").rglob("*")):
        if path.is_file() and path.suffix.lower() in {".html", ".css", ".js"}:
            try:
                parts.append(path.read_text(encoding="utf-8"))
            except UnicodeDecodeError as exc:
                raise CandidateFailure(f"built text asset is not UTF-8: {path.name}") from exc
    return "\n".join(parts)


def _visible_text(markup: str) -> str:
    value = re.sub(r"<(script|style)\b[^>]*>.*?</\1\s*>", " ", markup, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def _number(value: Any) -> float:
    match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
    if not match:
        raise CandidateFailure(f"value has no numeric price: {value!r}")
    return float(match.group())


def _verify_chrome() -> None:
    if not CHROME_PATH.is_file():
        raise HarnessFault(f"frozen Chrome is missing: {CHROME_PATH}")
    actual = _sha256(CHROME_PATH)
    if actual != CHROME_SHA256:
        raise HarnessFault(f"frozen Chrome hash mismatch: {actual}")


def _probe(repo: Path, javascript: str, viewport: tuple[int, int] = (1440, 900), html_file: str = "index.html") -> Any:
    _verify_chrome()
    source = (repo / "dist" / html_file).resolve()
    try:
        source.relative_to((repo / "dist").resolve())
    except ValueError as exc:
        raise HarnessFault("browser artifact escaped dist") from exc
    if not source.is_file():
        raise CandidateFailure(f"missing browser artifact dist/{html_file}")
    with tempfile.TemporaryDirectory(prefix="rq4-browser-") as directory:
        temporary = Path(directory)
        site = temporary / "site"
        shutil.copytree(repo / "dist", site)
        page = site / html_file
        document = page.read_text(encoding="utf-8")
        injected = """<script>(async()=>{try{const value=await(async()=>{%s})();const p=document.createElement('pre');p.id='rq4-probe';p.textContent=JSON.stringify({ok:true,value});document.body.replaceChildren(p)}catch(e){const p=document.createElement('pre');p.id='rq4-probe';p.textContent=JSON.stringify({ok:false,error:String(e&&e.stack||e)});document.body.replaceChildren(p)}})();</script>""" % javascript
        if re.search(r"</body\s*>", document, flags=re.I):
            document = re.sub(r"</body\s*>", injected + "</body>", document, count=1, flags=re.I)
        else:
            document += injected
        page.write_text(document, encoding="utf-8")
        width, height = viewport
        command = [
            str(CHROME_PATH), "--headless=new", "--disable-gpu", "--no-sandbox",
            "--disable-dev-shm-usage", "--disable-background-networking", "--disable-component-update",
            "--disable-default-apps", "--disable-extensions", "--disable-sync", "--metrics-recording-only",
            "--mute-audio", "--hide-scrollbars", "--force-color-profile=srgb", "--force-device-scale-factor=1",
            "--host-resolver-rules=MAP * 0.0.0.0, EXCLUDE localhost", f"--window-size={width},{height}",
            "--virtual-time-budget=1800", f"--user-data-dir={temporary / 'profile'}", "--dump-dom", page.as_uri(),
        ]
        process = _run(command, repo, 35)
        if process.returncode != 0:
            raise HarnessFault(f"frozen Chrome failed: {process.stderr[-1200:]}")
        match = re.search(r'<pre id="rq4-probe">(.*?)</pre>', process.stdout, flags=re.S)
        if not match:
            raise CandidateFailure("browser probe produced no result")
        try:
            payload = json.loads(html.unescape(match.group(1)))
        except json.JSONDecodeError as exc:
            raise CandidateFailure("browser probe returned malformed JSON") from exc
        if not payload.get("ok"):
            raise CandidateFailure(f"browser probe error: {payload.get('error')}")
        return payload.get("value")


def _t001(repo: Path) -> list[dict[str, Any]]:
    app = _app(repo)
    routes = {(str(r.get("method", "")).upper(), r.get("path")) for r in app.routes()}
    _assert(("POST", "/api/quotes") not in routes, "former instant-quote route remains exposed")
    response = app.request("POST", "/api/quotes", {"square_feet": 1800, "package": "basic"})
    _assert(response.get("status") == 404, "former instant-quote destination still succeeds")
    gallery = app.request("GET", "/api/gallery")
    _assert(gallery.get("status") == 200, "gallery behavior is no longer available")
    pricing = _feature(_catalog(repo), "package-pricing-by-square-footage")
    _assert(bool(pricing.get("attributes")), "current package pricing catalog is missing")
    text = _built_text(repo).lower()
    _assert("instant quote" not in text and "instant-quote" not in text and "calculator" not in text,
            "built site still exposes instant-quote calculator content")
    return [{"test_id": "T001-AC001-OBS001", "status": "PASS"}]


def _quote_cases(repo: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    app = _app(repo)
    cases = [(1200, "under_1200_sqft"), (1201, "1201_2400_sqft"), (2401, "2401_3600_sqft"), (3601, "3600_plus_sqft")]
    results = []
    for square_feet, category in cases:
        response = app.request("POST", "/api/quotes", {"square_feet": square_feet, "package": "basic"})
        _assert(response.get("status") == 201, f"quote request failed for {square_feet} sqft")
        body = response.get("body", {})
        _assert(body.get("category") == category, f"wrong square-footage category for {square_feet}")
        results.append(body)
    feature = _feature(_catalog(repo), "package-pricing-by-square-footage")
    return results, feature.get("attributes") or {}


def _t003(repo: Path) -> list[dict[str, Any]]:
    results, attrs = _quote_cases(repo)
    matrix = attrs.get("basic_package_prices_by_square_footage")
    _assert(isinstance(matrix, dict), "built pricing catalog has no Basic square-footage matrix")
    for result in results:
        expected = _number(matrix.get(result["category"]))
        _assert(float(result.get("base_price_usd")) == expected, "returned quote is not sourced from its matrix cell")
    text = _visible_text(_built_text(repo)).lower().replace("–", "-")
    patterns = (r"under\s*1,?200", r"1,?201\s*-\s*2,?400", r"2,?401\s*-\s*3,?600", r"3,?600\s*\+")
    _assert(all(re.search(pattern, text) for pattern in patterns), "pricing page does not present all square-footage bands")
    return [{"test_id": "T003-AC001-OBS001", "categories": [r["category"] for r in results]}, {"test_id": "T003-AC001-OBS002", "status": "PASS"}]


def _t004(repo: Path) -> list[dict[str, Any]]:
    attrs = _feature(_catalog(repo), "package-pricing-by-square-footage").get("attributes") or {}
    _assert(attrs.get("package_count") == 4, "built pricing catalog does not define four packages")
    expected = ["under 1200 sqft", "1201-2400 sqft", "2401-3600 sqft", "3600+ sqft"]
    actual = [str(v).lower().replace("–", "-") for v in attrs.get("square_footage_categories", [])]
    _assert(actual == expected, "built pricing categories do not match the four specified bands")
    matrices = [value for key, value in attrs.items() if "prices_by_square_footage" in key and isinstance(value, dict)]
    _assert(len(matrices) == 4 and all(len(matrix) == 4 for matrix in matrices), "pricing matrix is not four packages by four prices")
    markup = _built_text(repo)
    visible = _visible_text(markup)
    prices = re.findall(r"(?:USD\s*|\$)\s*\d[\d,]*(?:\.\d{2})?", visible, flags=re.I)
    _assert(len(prices) >= 16, "built pricing surface does not display sixteen predefined price cells")
    lower = markup.lower()
    _assert(not re.search(r"<input\b[^>]*(?:name|id)=[\"'][^\"']*square[_ -]?feet", lower), "pricing surface still exposes calculator square-footage input")
    _assert(not re.search(r"<button\b[^>]*>\s*calculate\b", lower), "pricing surface still exposes a Calculate action")
    return [{"test_id": "T004-AC001-OBS001", "price_cells": len(prices)}, {"test_id": "T004-AC002-OBS002", "status": "PASS"}]


def _t005(repo: Path) -> list[dict[str, Any]]:
    results, attrs = _quote_cases(repo)
    expected = [390.0, 620.0, 860.0, 1120.0]
    actual = [float(item.get("base_price_usd")) for item in results]
    _assert(actual == expected, f"Basic API prices are {actual}, expected {expected}")
    matrix = attrs.get("basic_package_prices_by_square_footage") or {}
    keys = ["under_1200_sqft", "1201_2400_sqft", "2401_3600_sqft", "3600_plus_sqft"]
    _assert([_number(matrix.get(key)) for key in keys] == expected, "built Basic catalog row has wrong prices")
    visible = _visible_text(_built_text(repo))
    start = visible.lower().find("basic")
    _assert(start >= 0, "built pricing surface has no Basic package row")
    tail = visible[start:]
    positions = [tail.find(str(int(value))) for value in expected]
    _assert(all(position >= 0 for position in positions) and positions == sorted(positions), "Basic displayed prices are missing or out of order")
    return [{"test_id": "T005-AC001-OBS001", "prices": actual}, {"test_id": "T005-AC001-OBS002", "status": "PASS"}]


def _t008(repo: Path) -> list[dict[str, Any]]:
    gallery = _app(repo).request("GET", "/api/gallery")
    _assert(gallery.get("status") == 200, "gallery API failed")
    tabs = [str(value).strip().lower().replace("_", " ") for value in gallery.get("body", {}).get("tabs", [])]
    _assert(tabs == ["photos", "twilights", "floor plans", "3d tour"], f"gallery tabs are {tabs}")
    script = r"""
const vis=e=>{if(!e)return false;const s=getComputedStyle(e),r=e.getBoundingClientRect();return s.display!=='none'&&s.visibility!=='hidden'&&r.width>0&&r.height>0};
const regions=[...document.querySelectorAll('section,main,article,div')].filter(vis);
const ident=e=>[e.id,e.className,e.getAttribute('data-page'),e.getAttribute('data-gallery-portfolio'),e.getAttribute('data-home-portfolio'),e.getAttribute('aria-label')].filter(Boolean).join(' ').toLowerCase();
const gallery=regions.find(e=>/gallery/.test(ident(e))&&e.querySelector('video')&&e.querySelector('img,picture'));
const home=regions.find(e=>/(home|portfolio)/.test(ident(e))&&e.querySelector('video')&&e.querySelector('img,picture')&&e!==gallery);
const tabs=[...document.querySelectorAll('[role=tab],[data-gallery-tab]')].filter(vis).map(e=>(e.getAttribute('aria-label')||e.textContent).trim().toLowerCase().replaceAll('_',' '));
const video=home&&home.querySelector('video'), picture=home&&home.querySelector('img,picture');
const vr=video&&video.getBoundingClientRect(),pr=picture&&picture.getBoundingClientRect();
const horizontal=!!(vr&&pr&&((vr.right<=pr.left)||(pr.right<=vr.left))&&Math.min(vr.bottom,pr.bottom)>Math.max(vr.top,pr.top));
return {galleryIntegrated:!!gallery,homeIntegrated:!!home,horizontal,tabs};
"""
    value = _probe(repo, script)
    _assert(value.get("galleryIntegrated"), "video and picture do not share the gallery portfolio region")
    _assert(value.get("homeIntegrated"), "homepage video and portfolio photo do not share a distinct section")
    _assert(value.get("horizontal"), "homepage video/photo boxes are not side-by-side with overlapping vertical ranges")
    if value.get("tabs"):
        _assert(value["tabs"] == tabs, "rendered gallery tabs disagree with public gallery behavior")
    return [{"test_id": "T008-AC001-OBS001", "tabs": tabs}, {"test_id": "T008-AC002-OBS002", "status": "PASS"}]


def _t009(repo: Path) -> list[dict[str, Any]]:
    script = r"""
const videos=[...document.querySelectorAll('video')];
const info=videos.map(v=>{const c=v.closest('[data-page],section,main,article,div')||v.parentElement;const src=v.currentSrc||v.getAttribute('src')||v.querySelector('source')?.getAttribute('src')||'';const context=[c?.id,c?.className,c?.getAttribute('data-page'),c?.getAttribute('aria-label')].filter(Boolean).join(' ').toLowerCase();const designation=[v.getAttribute('data-role'),v.getAttribute('data-placeholder'),v.getAttribute('aria-label'),v.title,c?.textContent].filter(Boolean).join(' ').toLowerCase();return {src,context,placeholder:designation.includes('temporary placeholder')};});
return {home:info.find(x=>/(home|homepage)/.test(x.context)),gallery:info.find(x=>/gallery/.test(x.context)),count:info.length};
"""
    value = _probe(repo, script)
    for context in ("home", "gallery"):
        item = value.get(context)
        _assert(bool(item), f"built page has no {context} video context")
        _assert(item.get("src") == COASTAL_URL, f"{context} video does not use the supplied Coastal Aerial URL")
        _assert(item.get("placeholder"), f"{context} video is not designated as a temporary placeholder")
    return [{"test_id": "T009-AC001-OBS001", "video_count": value.get("count")}]


def _quote_form_file(repo: Path) -> str:
    aliases = ("name", "company", "phone", "email", "job description")
    candidates = []
    for path in sorted((repo / "dist").rglob("*.html")):
        visible = _visible_text(path.read_text(encoding="utf-8")).lower()
        score = sum(alias in visible for alias in aliases)
        if score == len(aliases):
            candidates.append(path)
    _assert(len(candidates) == 1, "expected exactly one built Get a Quote form page")
    return candidates[0].relative_to(repo / "dist").as_posix()


def _t010(repo: Path) -> list[dict[str, Any]]:
    page = _quote_form_file(repo)
    markup = _built_text(repo)
    lower = markup.lower()
    _assert("calendly.com" not in lower and "assets.calendly" not in lower, "quote flow contains a Calendly URL or script")
    index = (repo / "dist" / "index.html").read_text(encoding="utf-8")
    cta = re.search(r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>[^<]*book\s+a\s+session[^<]*</a>", index, flags=re.I)
    _assert(bool(cta), "Book a Session CTA is missing or is not a link")
    href = html.unescape(cta.group(1)).lower()
    _assert("quote" in href or page.lower() in href or ("#" in href and "quote" in href.split("#", 1)[1]), "Book a Session CTA does not target the Get a Quote page")
    script = r"""
const norm=s=>(s||'').trim().toLowerCase().replace(/[^a-z0-9]+/g,' ');
const forms=[...document.querySelectorAll('form')];
const form=forms.find(f=>['name','company','phone number','email','job description'].every(w=>norm(f.textContent+' '+[...f.elements].map(e=>[e.name,e.id,e.getAttribute('aria-label'),e.placeholder].join(' ')).join(' ')).includes(w)));
if(!form)return {found:false};
const field=label=>[...form.querySelectorAll('input,textarea')].find(e=>{const l=e.labels&&[...e.labels].map(x=>x.textContent).join(' ');return norm([l,e.getAttribute('aria-label'),e.placeholder,e.name,e.id].join(' ')).includes(label)});
const names=['name','company','phone number','email','job description'];const fields=Object.fromEntries(names.map(n=>[n,field(n)]));
const root=getComputedStyle(document.documentElement),body=getComputedStyle(document.body);
return {found:true,present:Object.fromEntries(names.map(n=>[n,!!fields[n]])),required:Object.fromEntries(names.map(n=>[n,!!fields[n]?.required])),tokens:{ink:root.getPropertyValue('--ink').trim().toLowerCase(),accent:root.getPropertyValue('--accent').trim().toLowerCase(),paper:root.getPropertyValue('--paper').trim().toLowerCase()},font:body.fontFamily.toLowerCase()};
"""
    value = _probe(repo, script, html_file=page)
    _assert(value.get("found") and all(value.get("present", {}).values()), "quote form lacks one or more semantic fields")
    required = value.get("required", {})
    _assert(not required.get("company"), "Company field is incorrectly required")
    _assert(all(required.get(name) for name in ("name", "phone number", "email", "job description")), "one or more required quote fields are not marked required")
    tokens = value.get("tokens", {})
    _assert(tokens == {"ink": BRAND_TOKENS["--ink"], "accent": BRAND_TOKENS["--accent"], "paper": BRAND_TOKENS["--paper"]}, "quote page does not reuse frozen sitewide color tokens")
    _assert("system-ui" in value.get("font", ""), "quote page does not reuse the frozen sitewide typography")
    app = _app(repo)
    routes = [r for r in app.routes() if str(r.get("method", "")).upper() == "POST" and any(term in str(r.get("path", "")).lower() for term in ("quote", "request", "contact"))]
    payload = {"name": "Test Customer", "company": "", "phone_number": "+1-555-0100", "email": "customer@example.test", "job_description": "Photograph a four-room property"}
    accepted = None
    for route in routes:
        response = app.request("POST", route.get("path"), payload)
        body = response.get("body") if isinstance(response, dict) else None
        if response.get("status") == 201 and isinstance(body, dict) and all(key in body for key in payload):
            accepted = (route.get("path"), body)
            break
    _assert(accepted is not None, "no public quote-request POST route accepts and returns the required schema")
    _assert(accepted[1].get("company") == "", "optional empty Company value was not accepted")
    invalid_app = _app(repo)
    invalid = dict(payload)
    invalid.pop("email")
    rejected = invalid_app.request("POST", accepted[0], invalid)
    _assert(rejected.get("status") == 400, "quote request without Email was not rejected")
    return [{"test_id": "T010-AC001-OBS001", "page": page}, {"test_id": "T010-AC002-OBS002", "route": accepted[0]}, {"test_id": "T010-AC003-OBS003", "status": "PASS"}]


TARGETS: dict[str, Callable[[Path], list[dict[str, Any]]]] = {
    "44035087_T001": _t001, "44035087_T003": _t003, "44035087_T004": _t004,
    "44035087_T005": _t005, "44035087_T008": _t008, "44035087_T009": _t009,
    "44035087_T010": _t010,
}


def _write_result(path: Path, result: dict[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main(target_id: str) -> int:
    parser = argparse.ArgumentParser(description="Hidden deterministic RQ4 validator")
    parser.add_argument("--component", required=True, choices=("build", "target", "regression"))
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    args = parser.parse_args()
    result = {"schema_version": SCHEMA_VERSION, "target_id": target_id, "component": args.component, "status": "HARNESS_FAULT", "checks": [], "failures": []}
    exit_code = 2
    try:
        repo = _repo(args.repo)
        if args.component == "build":
            result["checks"] = _build(repo)
        elif args.component == "regression":
            result["checks"] = _regression(repo)
        else:
            result["checks"] = TARGETS[target_id](repo)
        result["status"] = "PASS"
        exit_code = 0
    except CandidateFailure as exc:
        result["status"] = "CANDIDATE_FAIL"
        result["failures"] = [str(exc)]
        exit_code = 1
    except HarnessFault as exc:
        result["status"] = "HARNESS_FAULT"
        result["failures"] = [str(exc)]
        exit_code = 2
    except Exception as exc:
        result["status"] = "HARNESS_FAULT"
        result["failures"] = [f"unexpected validator error: {type(exc).__name__}: {exc}"]
        exit_code = 2
    try:
        _write_result(args.result, result)
    except OSError as exc:
        result["status"] = "HARNESS_FAULT"
        result["failures"] = [f"cannot write result: {exc}"]
        exit_code = 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return exit_code

