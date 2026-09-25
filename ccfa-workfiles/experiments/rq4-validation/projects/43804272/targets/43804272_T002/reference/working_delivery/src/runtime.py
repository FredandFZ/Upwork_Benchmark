
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil

from application import create_app
from current_state import FEATURES, PROJECT
from platform_build import PLATFORM_BUILD


def feature_catalog():
    return deepcopy(FEATURES)


def get_feature(slug):
    for feature in FEATURES:
        if feature["slug"] == slug:
            return deepcopy(feature)
    raise KeyError(slug)


def simulate(slug):
    feature = get_feature(slug)
    execution = feature.get("execution") or {}
    return {"slug": slug, "status": execution.get("status", "AVAILABLE"),
            "observed_behavior": execution.get("observed_behavior"),
            "attributes": deepcopy(feature.get("attributes") or {})}


def build(output="dist"):
    output = Path(output)
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    assets = Path(__file__).resolve().parents[1] / "web"
    page = "mobile-preview.html" if PROJECT["renderer"] == "mobile" else "index.html"
    shutil.copyfile(assets / "index.html", output / page)
    shutil.copyfile(assets / "app.js", output / "app.js")
    catalog_name = "app-config.json" if PROJECT["renderer"] == "mobile" else "catalog.json"
    payload = {"project": {"title": PROJECT["title"], "renderer": PROJECT["renderer"]},
               "routes": create_app().routes(), "features": feature_catalog(),
               "platform_build": deepcopy(PLATFORM_BUILD)}
    (output / catalog_name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shared_asset = Path(__file__).resolve().parents[1] / "resources" / "tutorial-background.svg"
    shutil.copyfile(shared_asset, output / "tutorial-background.svg")
    package_manifest = {
        "optimization_priority": PLATFORM_BUILD["optimization_priority"],
        "assets": [{"path": "tutorial-background.svg", "shared_across_locales": True,
                    "bytes": (output / "tutorial-background.svg").stat().st_size}],
        "localized_tutorial_images": [],
        "android_packaging": PLATFORM_BUILD["android_packaging"],
        "ios_packaging": PLATFORM_BUILD["ios_packaging"],
    }
    (output / "package-manifest.json").write_text(
        json.dumps(package_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return output


def check(output="dist"):
    output = Path(output)
    expected = [output / item.removeprefix("dist/") for item in PROJECT["primary_artifacts"]]
    missing = [str(path) for path in expected if not path.is_file() or not path.stat().st_size]
    if missing:
        raise RuntimeError(f"missing build artifacts: {missing}")
    page = output / ("mobile-preview.html" if PROJECT["renderer"] == "mobile" else "index.html")
    if "app.js" not in page.read_text(encoding="utf-8"):
        raise RuntimeError("interactive application script is missing")
    manifest = json.loads((output / "package-manifest.json").read_text(encoding="utf-8"))
    if manifest["localized_tutorial_images"] or len(manifest["assets"]) != 1:
        raise RuntimeError("localized tutorial assets are duplicated")
    return {"renderer": PROJECT["renderer"], "artifact_count": len(expected),
            "feature_count": len(FEATURES), "route_count": len(create_app().routes())}
