from __future__ import annotations

import argparse
from html.parser import HTMLParser
import importlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Callable, Iterator


SCHEMA_VERSION = "rq4-deterministic-validator-result-v1"
OLD_VIDEO = "https://video.cedar-meadow.example/watch/e0023"
NEW_VIDEO = "https://cedar-meadow.example/resource/e0024"


class CandidateFailure(RuntimeError):
    pass


class HarnessFault(RuntimeError):
    pass


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise CandidateFailure(message)


def _norm(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


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
    for name in ("mobile-preview.html", "app-config.json"):
        path = repo / "dist" / name
        if not path.is_file() or path.stat().st_size == 0:
            raise CandidateFailure(f"missing built artifact dist/{name}")
    return checks


def _regression(repo: Path) -> list[dict[str, Any]]:
    process = _run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], repo)
    if process.returncode != 0:
        raise CandidateFailure(f"repository regression tests failed: {(process.stderr or process.stdout)[-1800:]}")
    return [{"test_id": "REG-001", "exit_code": 0}]


def _import(repo: Path, module_name: str):
    src = str(repo / "src")
    sys.path.insert(0, src)
    try:
        for name in (module_name, "application", "domain", "platform_build", "current_state"):
            sys.modules.pop(name, None)
        return importlib.import_module(module_name)
    except Exception as exc:
        raise CandidateFailure(f"cannot import public module {module_name}: {exc}") from exc
    finally:
        if sys.path and sys.path[0] == src:
            sys.path.pop(0)


def _app(repo: Path):
    return _import(repo, "application").create_app()


def _platform_build(repo: Path) -> dict[str, Any]:
    value = getattr(_import(repo, "platform_build"), "PLATFORM_BUILD", None)
    _assert(isinstance(value, dict), "platform_build.PLATFORM_BUILD is not a mapping")
    return value


def _nodes(value: Any, path: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], Any]]:
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _nodes(child, path + (str(key),))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _nodes(child, path + (str(index),))


def _json_documents(repo: Path) -> list[tuple[Path, Any]]:
    result = []
    for path in sorted((repo / "dist").rglob("*.json")):
        try:
            result.append((path, json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, json.JSONDecodeError) as exc:
            raise CandidateFailure(f"generated JSON is invalid: {path.name}: {exc}") from exc
    return result


def _locale_values(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    result = []
    for item in value:
        if isinstance(item, str):
            result.append(_norm(item).replace("_", "-"))
        elif isinstance(item, dict):
            locale = next((item.get(key) for key in ("locale", "language_tag", "tag", "code") if item.get(key)), None)
            if locale is None:
                return None
            result.append(_norm(locale).replace("_", "-"))
        else:
            return None
    return result


def _locale_index(repo: Path, platform: str) -> list[str]:
    sources: list[tuple[str, Any]] = [("platform_build", _platform_build(repo))]
    sources.extend((path.as_posix(), value) for path, value in _json_documents(repo))
    candidates: list[list[str]] = []
    for source_name, source in sources:
        for path, value in _nodes(source):
            signature = _norm(" ".join((source_name, *path)))
            if platform in signature and ("locale" in signature or "language" in signature) and ("resource" in signature or "index" in signature or "locales" in signature or "languages" in signature):
                locales = _locale_values(value)
                if locales:
                    candidates.append(locales)
    _assert(bool(candidates), f"no generated {platform} locale resource index exists")
    return max(candidates, key=len)


def _optimization_record(model: dict[str, Any], platform: str) -> dict[str, Any]:
    candidates = []
    for path, value in _nodes(model):
        signature = _norm(" ".join(path))
        if isinstance(value, dict) and platform in signature and ("size" in signature or "optim" in signature):
            candidates.append(value)
    _assert(bool(candidates), f"platform build has no {platform} size-optimization record")
    return max(candidates, key=lambda value: len(json.dumps(value, sort_keys=True)))


def _recursive_value(value: Any, names: set[str]) -> Any:
    for path, child in _nodes(value):
        if path and _norm(path[-1]).replace("-", "_") in names and not isinstance(child, (dict, list)):
            return child
    return None


def _variant(model: dict[str, Any], record: dict[str, Any], platform: str) -> str:
    direct = _recursive_value(record, {"build_variant", "variant", "configuration"})
    if direct is not None:
        return _norm(direct)
    for path, value in _nodes(model):
        signature = _norm(" ".join(path))
        if platform in signature and path and _norm(path[-1]).replace("-", "_") in {"build_variant", "variant", "configuration"} and not isinstance(value, (dict, list)):
            return _norm(value)
    return ""


def _t002(repo: Path) -> list[dict[str, Any]]:
    model = _platform_build(repo)
    checks = []
    for platform in ("android", "ios"):
        record = _optimization_record(model, platform)
        priority = _recursive_value(record, {"optimization_priority", "active_optimization_priority", "size_priority"})
        _assert(_norm(priority).strip(".") in {"smallest possible app size", "achieve the smallest possible app size"}, f"{platform} does not make smallest app size the active priority")
        _assert(_variant(model, record, platform) == "production", f"{platform} size optimization is not scoped to production")
        checks.append({"test_id": f"T002-AC00{1 if platform == 'android' else 2}-OBS00{1 if platform == 'android' else 2}", "platform": platform})
    android = _locale_index(repo, "android")
    ios = _locale_index(repo, "ios")
    _assert(len(android) == len(set(android)) == 77, "Android locale index is not 77 unique entries")
    _assert(len(ios) == len(set(ios)) == 40, "iOS locale index is not 40 unique entries")
    checks.append({"test_id": "T002-AC003-OBS003", "android": 77, "ios": 40})
    return checks


def _manifest(repo: Path, kind: str, platform: str | None = None) -> tuple[Path, dict[str, Any]]:
    candidates = []
    for file, document in _json_documents(repo):
        for path, value in _nodes(document):
            if not isinstance(value, dict):
                continue
            signature = _norm(" ".join((file.as_posix(), *path)))
            if kind == "media":
                has_format = any(_norm(key).replace("-", "_") in {"media_format", "format"} for key in value)
                if "media" in signature and "manifest" in signature and has_format:
                    candidates.append((file, value))
            else:
                key_signature = _norm(" ".join(str(key) for key in value))
                has_asset_index = any(term in key_signature for term in ("asset", "resource", "file"))
                if platform and platform in signature and "package" in signature and ("manifest" in signature or "asset" in signature) and has_asset_index:
                    candidates.append((file, value))
    label = "media" if kind == "media" else f"{platform} package"
    _assert(len(candidates) == 1, f"expected exactly one generated {label} manifest record, found {len(candidates)}")
    return candidates[0]


def _field(record: dict[str, Any], names: set[str]) -> Any:
    for key, value in record.items():
        if _norm(key).replace("-", "_") in names:
            return value
    return _recursive_value(record, names)


def _platforms(record: dict[str, Any]) -> list[str]:
    value = _field(record, {"enabled_platforms", "media_platforms", "platforms"})
    _assert(isinstance(value, list), "media manifest has no enabled platform list")
    return sorted({_norm(item).upper() for item in value})


def _asset_strings(record: dict[str, Any]) -> list[str]:
    result = []
    for path, value in _nodes(record):
        signature = _norm(" ".join(path))
        if isinstance(value, str) and any(term in signature for term in ("asset", "file", "resource", "path")):
            result.append(value)
    return result


def _tutorial_images(repo: Path, platform: str) -> tuple[int, str]:
    path, record = _manifest(repo, "package", platform)
    strings = _asset_strings(record)
    platform_paths = [p.relative_to(repo / "dist").as_posix() for p in (repo / "dist").rglob("*") if p.is_file() and platform in p.relative_to(repo / "dist").as_posix().casefold()]
    combined = strings + platform_paths
    image = re.compile(r"(?:tutorial|how[-_ ]?to).+\.(?:png|jpe?g|gif|webp|heic)$", re.I)
    return sum(bool(image.search(value)) for value in combined), json.dumps(record, ensure_ascii=False, sort_keys=True)


class _ControlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[dict[str, Any]] = []
        self.controls: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() in {"a", "button"}:
            item = {"tag": tag.casefold(), "attrs": {k.casefold(): v or "" for k, v in attrs}, "text": []}
            self.stack.append(item)

    def handle_data(self, data: str) -> None:
        for item in self.stack:
            item["text"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if self.stack and self.stack[-1]["tag"] == tag.casefold():
            self.controls.append(self.stack.pop())


def _html_launches(repo: Path) -> dict[str, dict[str, str]]:
    parser = _ControlParser()
    for path in sorted((repo / "dist").rglob("*.html")):
        parser.feed(path.read_text(encoding="utf-8"))
    launches: dict[str, dict[str, str]] = {}
    for control in parser.controls:
        attrs = control["attrs"]
        text = _norm(" ".join(control["text"]))
        signature = _norm(" ".join((text, *attrs.keys(), *attrs.values())))
        if not ("how to" in signature or "how-to" in signature or "tutorial" in signature):
            continue
        resource = next((attrs.get(key) for key in ("href", "data-resource", "data-url", "data-launch-target") if attrs.get(key)), "")
        kind = next((attrs.get(key) for key in ("data-media-kind", "data-media-format", "data-kind") if attrs.get(key)), "")
        platform_signature = _norm(" ".join((attrs.get("data-platform", ""), attrs.get("data-platforms", ""), attrs.get("aria-label", ""), text)))
        assigned = [platform for platform in ("android", "ios") if platform in platform_signature]
        if not assigned:
            assigned = ["all"]
        for platform in assigned:
            launches[platform] = {"resource": resource, "kind": _norm(kind)}
    return launches


def _response_launch(body: Any) -> dict[str, str] | None:
    if not isinstance(body, dict):
        return None
    resource = _field(body, {"resource", "video_resource", "url", "launch_target", "target"})
    kind = _field(body, {"media_format", "media_kind", "kind", "format"})
    if isinstance(resource, str) and resource:
        return {"resource": resource, "kind": _norm(kind)}
    return None


def _public_launch(repo: Path, platform: str) -> dict[str, str] | None:
    app = _app(repo)
    service = getattr(app, "service", None)
    for name in ("open_how_to", "launch_how_to", "how_to", "open_tutorial", "launch_tutorial"):
        method = getattr(service, name, None)
        if callable(method):
            try:
                result = method(platform)
            except Exception as exc:
                raise CandidateFailure(f"public {name} failed for {platform}: {exc}") from exc
            launch = _response_launch(result)
            if launch:
                return launch
    for route in app.routes():
        path = str(route.get("path", ""))
        if not any(term in path.casefold() for term in ("how-to", "how_to", "tutorial", "media")):
            continue
        method = str(route.get("method", "GET")).upper()
        response = app.request(method, path, {"platform": platform}, {"platform": platform})
        if isinstance(response, dict) and response.get("status") == 200:
            launch = _response_launch(response.get("body"))
            if launch:
                return launch
    return None


def _launch(repo: Path, platform: str) -> dict[str, str]:
    public = _public_launch(repo, platform)
    if public:
        return public
    html = _html_launches(repo)
    launch = html.get(platform) or html.get("all")
    _assert(bool(launch and launch.get("resource")), f"no public How To Use launch interaction for {platform}")
    return launch


def _t003(repo: Path) -> list[dict[str, Any]]:
    _path, media = _manifest(repo, "media")
    _assert(_norm(_field(media, {"media_format", "format"})) == "youtube_video", "generated media format is not youtube_video")
    _assert(_platforms(media) == ["IOS"], "generated media manifest is not scoped only to iOS")
    launch = _launch(repo, "ios")
    _assert((launch.get("kind") or "youtube_video") == "youtube_video", "iOS How To interaction does not open YouTube video media")
    count, package_text = _tutorial_images(repo, "ios")
    _assert(count == 0, "iOS package still contains localized tutorial-image assets")
    _assert(not re.search(r"localized[_ -]?tutorial[_ -]?image|tutorial[_ -]?image[_ -]?strategy", package_text, flags=re.I), "iOS package manifest references the removed tutorial-image strategy")
    return [{"test_id": "T003-AC001-OBS001", "status": "PASS"}, {"test_id": "T003-AC002-OBS002", "tutorial_images": 0}, {"test_id": "T003-AC003-OBS003", "platforms": ["IOS"]}]


def _t004(repo: Path) -> list[dict[str, Any]]:
    launches = {platform: _launch(repo, platform) for platform in ("android", "ios")}
    for platform, launch in launches.items():
        _assert(launch.get("resource") == OLD_VIDEO, f"{platform} launches the wrong How To resource")
    for platform in ("android", "ios"):
        count, _text = _tutorial_images(repo, platform)
        _assert(count == 0, f"{platform} package still contains tutorial-image assets")
    _path, media = _manifest(repo, "media")
    _assert(_norm(_field(media, {"media_format", "format"})) == "shared_video", "media manifest format is not shared_video")
    _assert(_platforms(media) == ["ANDROID", "IOS"], "media manifest is not enabled for Android and iOS")
    _assert(_field(media, {"video_resource", "resource", "url"}) == OLD_VIDEO, "media manifest has the wrong video resource")
    return [{"test_id": "T004-AC001-OBS001", "resource": OLD_VIDEO}, {"test_id": "T004-AC002-OBS002", "status": "PASS"}, {"test_id": "T004-AC003-OBS003", "status": "PASS"}]


def _t005(repo: Path) -> list[dict[str, Any]]:
    _path, media = _manifest(repo, "media")
    _assert(_norm(_field(media, {"video_hosting_channel", "hosting_channel", "channel"})) == "client_main_youtube_channel", "media manifest has the wrong hosting channel")
    _assert(_norm(_field(media, {"video_delivery_method", "delivery_method", "delivery"})) == "external_streaming", "media manifest delivery is not external_streaming")
    _assert(_platforms(media) == ["ANDROID", "IOS"], "media manifest is not enabled for Android and iOS")
    _assert(_norm(_field(media, {"media_format", "format"})) == "shared_video", "media manifest format is not shared_video")
    return [{"test_id": "T005-AC001-OBS001", "status": "PASS"}]


def _t006(repo: Path) -> list[dict[str, Any]]:
    launches = {platform: _launch(repo, platform) for platform in ("android", "ios")}
    _path, media = _manifest(repo, "media")
    media_resource = _field(media, {"video_resource", "resource", "url"})
    resources = [media_resource, launches["android"].get("resource"), launches["ios"].get("resource")]
    _assert(resources == [NEW_VIDEO, NEW_VIDEO, NEW_VIDEO], f"new integration resource does not occur in all three launch records: {resources}")
    _assert(OLD_VIDEO not in resources, "superseded e0023 URL remains in media/launch records")
    return [{"test_id": "T006-AC001-OBS001", "resource": NEW_VIDEO}, {"test_id": "T006-AC002-OBS002", "new_resource_occurrences": 3}]


TARGETS: dict[str, Callable[[Path], list[dict[str, Any]]]] = {
    "43804272_T002": _t002,
    "43804272_T003": _t003,
    "43804272_T004": _t004,
    "43804272_T005": _t005,
    "43804272_T006": _t006,
}


def _write_result(path: Path, result: dict[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main(target_id: str) -> int:
    parser = argparse.ArgumentParser(description="Hidden deterministic mobile-platform RQ4 validator")
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

