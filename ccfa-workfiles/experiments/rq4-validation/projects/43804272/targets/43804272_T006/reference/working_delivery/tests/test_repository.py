from pathlib import Path
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from current_state import FEATURES, PROJECT
from runtime import build, check, feature_catalog, get_feature, simulate


class RepositoryTest(unittest.TestCase):
    def test_catalog_has_unique_public_keys(self):
        slugs = [item["slug"] for item in feature_catalog()]
        self.assertEqual(len(slugs), len(set(slugs)))
        self.assertFalse(any("REQ_" in json.dumps(item) for item in FEATURES))

    def test_each_feature_is_executable(self):
        for item in FEATURES:
            self.assertEqual(get_feature(item["slug"])["title"], item["title"])
            self.assertIn("status", simulate(item["slug"]))

    def test_clean_build_and_artifact_check(self):
        with tempfile.TemporaryDirectory() as directory:
            build(directory)
            result = check(directory)
            self.assertEqual(result["renderer"], PROJECT["renderer"])
            self.assertEqual(result["feature_count"], len(FEATURES))


if __name__ == "__main__":
    unittest.main()
