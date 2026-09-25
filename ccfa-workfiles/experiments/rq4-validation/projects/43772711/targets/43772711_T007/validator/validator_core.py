from __future__ import annotations

import argparse
import colorsys
import hashlib
import html
from html.parser import HTMLParser
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any


SCHEMA_VERSION = "rq4-deterministic-validator-result-v1"
CHROME_PATH = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
CHROME_SHA256 = "e8bce39747ea63c9c7d4306f7635d2916c9ecb0cf913fbcf5e7acc4539b5b8a0"
VIEWPORTS = ((1440, 900), (768, 1024), (390, 844))


class CandidateFailure(RuntimeError):
    pass


class HarnessFault(RuntimeError):
    pass


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


def _run_candidate(command: list[str], repo: Path, timeout: int = 45) -> subprocess.CompletedProcess[str]:
    kwargs: dict[str, Any] = {
        "cwd": repo,
        "env": _safe_env(),
        "text": True,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "timeout": timeout,
    }
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000
    try:
        return subprocess.run(command, **kwargs)
    except subprocess.TimeoutExpired as exc:
        raise HarnessFault(f"command timeout after {timeout}s: {command[0]}") from exc
    except OSError as exc:
        raise HarnessFault(f"cannot launch {command[0]}: {exc}") from exc


def _require_repo(repo: Path) -> Path:
    repo = repo.resolve()
    if not repo.is_dir() or not (repo / "scripts" / "build.py").is_file():
        raise HarnessFault("repository path is missing scripts/build.py")
    return repo


def _component_build(repo: Path) -> list[dict[str, Any]]:
    checks = []
    for test_id, script in (("BUILD-001", "build.py"), ("BUILD-002", "check.py")):
        process = _run_candidate([sys.executable, str(repo / "scripts" / script)], repo)
        checks.append({"test_id": test_id, "exit_code": process.returncode})
        if process.returncode != 0:
            raise CandidateFailure(f"{script} failed: {(process.stderr or process.stdout)[-1200:]}")
    for name in ("index.html", "catalog.json"):
        path = repo / "dist" / name
        if not path.is_file() or path.stat().st_size == 0:
            raise CandidateFailure(f"missing built artifact dist/{name}")
    return checks


def _component_regression(repo: Path) -> list[dict[str, Any]]:
    process = _run_candidate(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], repo, 60
    )
    if process.returncode != 0:
        raise CandidateFailure(f"repository regression tests failed: {(process.stderr or process.stdout)[-1600:]}")
    return [{"test_id": "REG-001", "exit_code": 0}]


def _verify_chrome() -> None:
    if not CHROME_PATH.is_file():
        raise HarnessFault(f"frozen Chrome is missing: {CHROME_PATH}")
    actual = _sha256(CHROME_PATH)
    if actual != CHROME_SHA256:
        raise HarnessFault(f"frozen Chrome hash mismatch: {actual}")


def _probe(repo: Path, javascript_body: str, viewport: tuple[int, int], html_file: str = "index.html") -> Any:
    _verify_chrome()
    source = repo / "dist" / html_file
    if not source.is_file():
        raise CandidateFailure(f"missing browser artifact dist/{html_file}")
    with tempfile.TemporaryDirectory(prefix="rq4-browser-") as directory:
        temporary = Path(directory)
        site = temporary / "site"
        shutil.copytree(repo / "dist", site)
        page = site / html_file
        document = page.read_text(encoding="utf-8", errors="strict")
        probe = """<script>(async()=>{try{const value=await(async()=>{%s})();const p=document.createElement('pre');p.id='rq4-probe';p.textContent=JSON.stringify({ok:true,value});document.body.replaceChildren(p)}catch(e){const p=document.createElement('pre');p.id='rq4-probe';p.textContent=JSON.stringify({ok:false,error:String(e&&e.stack||e)});document.body.replaceChildren(p)}})();</script>""" % javascript_body
        if re.search(r"</body\s*>", document, flags=re.I):
            document = re.sub(r"</body\s*>", probe + "</body>", document, count=1, flags=re.I)
        else:
            document += probe
        page.write_text(document, encoding="utf-8")
        width, height = viewport
        command = [
            str(CHROME_PATH), "--headless=new", "--disable-gpu", "--no-sandbox",
            "--disable-dev-shm-usage", "--disable-background-networking",
            "--disable-component-update", "--disable-default-apps", "--disable-extensions",
            "--disable-sync", "--metrics-recording-only", "--mute-audio",
            "--hide-scrollbars", "--force-color-profile=srgb", "--force-device-scale-factor=1",
            "--host-resolver-rules=MAP * 0.0.0.0, EXCLUDE localhost",
            f"--window-size={width},{height}", "--virtual-time-budget=1500",
            f"--user-data-dir={temporary / 'profile'}", "--dump-dom", page.resolve().as_uri(),
        ]
        process = _run_candidate(command, repo, 30)
        if process.returncode != 0:
            raise HarnessFault(f"frozen Chrome failed: {process.stderr[-1200:]}")
        match = re.search(r'<pre id="rq4-probe">(.*?)</pre>', process.stdout, flags=re.S)
        if not match:
            raise CandidateFailure("browser probe did not produce a result; page script may be invalid")
        try:
            payload = json.loads(html.unescape(match.group(1)))
        except json.JSONDecodeError as exc:
            raise CandidateFailure("browser probe produced malformed JSON") from exc
        if not payload.get("ok"):
            raise CandidateFailure(f"browser probe error: {payload.get('error')}")
        return payload.get("value")


def _public_app(repo: Path):
    src = str(repo / "src")
    sys.path.insert(0, src)
    try:
        for name in ("application", "domain", "runtime", "current_state"):
            sys.modules.pop(name, None)
        module = importlib.import_module("application")
        return module.create_app()
    except Exception as exc:
        raise CandidateFailure(f"cannot create public application: {exc}") from exc
    finally:
        if sys.path and sys.path[0] == src:
            sys.path.pop(0)


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise CandidateFailure(message)


def _visible_geometry_script(extra: str = "") -> str:
    return r"""
const visible=e=>{if(!e)return false;const s=getComputedStyle(e),r=e.getBoundingClientRect();return s.display!=='none'&&s.visibility!=='hidden'&&r.width>0&&r.height>0};
const one=s=>[...document.querySelectorAll(s)].filter(visible);
""" + extra


def _test_t001(repo: Path) -> list[dict[str, Any]]:
    app = _public_app(repo)
    api = []
    for theme in ("light", "dark"):
        response = app.request("PATCH", "/api/ui-shell/theme", {"theme": theme})
        _assert(response.get("status") == 200, f"theme API rejected {theme}")
        _assert(response.get("body", {}).get("theme") == theme, f"theme API did not select {theme}")
        for key in ("header", "navigation", "footer"):
            _assert(bool(response.get("body", {}).get(key)), f"theme API omits {key} after selecting {theme}")
        api.append(theme)
    script = _visible_geometry_script(r"""
const selectors={header:'header,[role="banner"]',nav:'nav,[role="navigation"],aside[data-navigation]',main:'main,[role="main"],[data-main-canvas]',footer:'footer,[role="contentinfo"]'};
const counts=Object.fromEntries(Object.entries(selectors).map(([k,s])=>[k,one(s).length]));
const region=e=>{const s=getComputedStyle(e);return {font:s.fontFamily,fg:s.color,bg:s.backgroundColor,icons:e.querySelectorAll('svg,img,[role="img"],[data-icon],.icon').length}};
const themes={};for(const theme of ['light','dark']){document.documentElement.dataset.theme=theme;document.body.dataset.theme=theme;document.documentElement.classList.remove('light','dark');document.documentElement.classList.add(theme);themes[theme]={};for(const [k,s] of Object.entries(selectors)){const e=one(s)[0];themes[theme][k]=e?region(e):null}}
return {counts,themes};
""")
    value = _probe(repo, script, (1440, 900))
    for region in ("header", "nav", "main", "footer"):
        _assert(value["counts"].get(region) == 1, f"expected one visible {region} landmark")
    for theme in ("light", "dark"):
        for region in ("header", "nav", "footer"):
            style = value["themes"].get(theme, {}).get(region) or {}
            _assert(bool(style.get("font")), f"{region} has no computed font in {theme} mode")
            _assert(style.get("fg") not in (None, "rgba(0, 0, 0, 0)"), f"{region} has no foreground treatment in {theme} mode")
            _assert(style.get("bg") not in (None, "rgba(0, 0, 0, 0)"), f"{region} has no background treatment in {theme} mode")
            _assert(style.get("icons", 0) >= 1, f"{region} has no icon element in {theme} mode")
    return [{"test_id": "T001-AC001-OBS001", "status": "PASS"}, {"test_id": "T001-AC002-OBS002", "themes": api}, {"test_id": "T001-AC003-OBS003", "status": "PASS"}]


def _test_t002(repo: Path) -> list[dict[str, Any]]:
    checks = []
    script = _visible_geometry_script(r"""
const main=one('main,[role="main"],#landing,[data-page="landing"]')[0];
const shell=one('[data-shell],.shell,#shell,[data-workspace-shell]')[0];
const canvas=one('[data-main-canvas],.main-canvas,#main-canvas,[data-canvas]')[0];
const controls=[...document.querySelectorAll('button,input,select,a,[role="switch"],[tabindex]')].filter(e=>/(theme|light|dark)/i.test([e.id,e.className,e.getAttribute('name'),e.getAttribute('aria-label'),e.textContent].join(' ')));
const marker=[document.documentElement.dataset.pageTheme,document.documentElement.dataset.theme,document.body.dataset.pageTheme,document.body.dataset.theme,document.documentElement.className,document.body.className,document.querySelector('meta[name="color-scheme"]')?.content].filter(Boolean).join(' ');
let media=0;for(const sheet of document.styleSheets){try{for(const rule of sheet.cssRules){if(rule.type===CSSRule.MEDIA_RULE&&/(min|max)-width/.test(rule.conditionText))media++}}catch(e){}}
return {scroll:document.documentElement.scrollWidth,width:innerWidth,mainVisible:visible(main),themeMarker:/(light|dark)/i.test(marker),themeControls:controls.length,media,shell:visible(shell),canvas:visible(canvas)};
""")
    for viewport in VIEWPORTS:
        value = _probe(repo, script, viewport)
        _assert(value["scroll"] <= value["width"] + 1, f"horizontal overflow at {viewport}")
        _assert(value["mainVisible"], f"primary content hidden at {viewport}")
        checks.append({"test_id": "T002-AC001-OBS001", "viewport": list(viewport)})
    first = _probe(repo, script, VIEWPORTS[0])
    _assert(first["themeMarker"], "no page-assigned light/dark theme marker")
    _assert(first["themeControls"] == 0, "user-operable theme switch is present")
    _assert(first["media"] >= 1, "built page has no width-based responsive breakpoint rule")
    _assert(first["shell"] and first["canvas"], "shell container or distinct main canvas is missing")
    checks.extend([{"test_id": "T002-AC002-OBS002", "status": "PASS"}, {"test_id": "T002-AC003-OBS003", "media_rules": first["media"]}, {"test_id": "T002-AC004-OBS004", "status": "PASS"}])
    return checks


def _parse_color(value: str) -> tuple[float, float, float, float]:
    match = re.fullmatch(r"rgba?\(\s*([\d.]+)[, ]+\s*([\d.]+)[, ]+\s*([\d.]+)(?:\s*[,/]\s*([\d.]+))?\s*\)", value)
    if not match:
        raise CandidateFailure(f"unsupported computed color: {value!r}")
    red, green, blue = (float(match.group(i)) / 255.0 for i in (1, 2, 3))
    alpha = float(match.group(4)) if match.group(4) is not None else 1.0
    return red, green, blue, alpha


def _test_t007(repo: Path) -> list[dict[str, Any]]:
    script = _visible_geometry_script(r"""
const footer=one('footer,[role="contentinfo"]')[0];return {visible:visible(footer),color:footer?getComputedStyle(footer).backgroundColor:null};
""")
    checks = []
    for viewport in VIEWPORTS:
        value = _probe(repo, script, viewport)
        _assert(value["visible"], f"footer is not visible at {viewport}")
        red, green, blue, alpha = _parse_color(value["color"])
        hue, lightness, _saturation = colorsys.rgb_to_hls(red, green, blue)
        degrees = (hue * 360.0) % 360.0
        delta = abs((degrees - 290.0 + 180.0) % 360.0 - 180.0)
        _assert(abs(alpha - 1.0) <= 1e-9, f"footer is not opaque at {viewport}")
        _assert(delta <= 30.0, f"footer hue {degrees:.2f} is outside dark-purple range at {viewport}")
        _assert(lightness * 100.0 <= 45.0, f"footer lightness {lightness*100:.2f}% is too high at {viewport}")
        checks.append({"test_id": "T007-AC001-OBS001", "viewport": list(viewport), "rgba": value["color"], "hue": round(degrees, 4), "lightness_percent": round(lightness * 100.0, 4)})
    return checks


TARGET_TESTS = {
    "43772711_T001": _test_t001,
    "43772711_T002": _test_t002,
    "43772711_T007": _test_t007,
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
        repo = _require_repo(args.repo)
        if args.component == "build":
            result["checks"] = _component_build(repo)
        elif args.component == "regression":
            result["checks"] = _component_regression(repo)
        else:
            if not (repo / "dist" / "index.html").is_file():
                raise CandidateFailure("target test requires a successful build with dist/index.html")
            result["checks"] = TARGET_TESTS[target_id](repo)
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

