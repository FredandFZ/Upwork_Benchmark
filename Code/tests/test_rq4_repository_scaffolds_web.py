from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

from Code.rq4_repository_scaffolds_web import augment_web_repository


PROJECT_CASES = {
    "42204309": {
        "renderer": "web",
        "features": [
            {"slug": "coded-referral-commission", "title": "Commission", "attributes": {"commission_amount_usd": 12}},
            {"slug": "coded-referral-ticket-issuance", "title": "Tickets", "attributes": {"tickets_per_coded_referral_mint": 4, "reward_drawing_amount_usd": 1250}},
            {"slug": "eth-pricing-and-excess-refund", "title": "Price", "attributes": {"target_mint_price": "$30 equivalent"}},
            {"slug": "eth-wallet-mint-flow", "title": "ETH", "attributes": {}},
            {"slug": "usdc-wallet-mint-flow", "title": "USDC", "attributes": {}},
            {"slug": "email-magic-link-authentication", "title": "Email auth", "attributes": {}},
        ],
        "exercise": """
service = create_app().service
service.register_referral('owner', 'SAVE')
receipt = service.mint('buyer', 35, referral_code='SAVE')
print(json.dumps({'tickets': receipt['referral']['tickets'], 'refund': receipt['refund_usd_equivalent'], 'dashboard': service.dashboard('owner')}))
""",
    },
    "43772711": {
        "renderer": "web",
        "features": [
            {"slug": "additional-page-prototype-code", "title": "Pages", "attributes": {}, "contexts": ["SIGN_IN_PAGE", "ACCOUNT_PROVISIONING"]},
            {"slug": "admin-workspace-shell-styling", "title": "Shell", "attributes": {"theme_modes": ["light", "dark"]}, "contexts": ["ADMIN_WORKSPACE"]},
            {"slug": "admin-workspace-panel-navigation", "title": "Panel", "attributes": {"shell_navigation_panel": {"collapsible": True}}, "contexts": ["ADMIN_WORKSPACE"]},
        ],
        "exercise": """
service = create_app().service
account = service.provision_account('admin@example.test', 'Acme')
workspace = service.update_workspace(theme='dark', navigation_collapsed=True)
print(json.dumps({'status': account['status'], 'workspace': workspace}))
""",
    },
    "43804272": {
        "renderer": "mobile",
        "features": [
            {"slug": "how-to-measurement-instructions", "title": "Measure", "attributes": {"measurement_sequence": [{"step": 1, "name": "Bend"}]}},
            {"slug": "right-to-left-layout-support", "title": "RTL", "attributes": {}},
        ],
        "exercise": """
service = create_app().service
measurement = service.measure([2, -9, 4])
locale = service.set_locale('ar')
print(json.dumps({'peak': measurement['peak_degrees'], 'direction': locale['direction']}))
""",
    },
    "44035087": {
        "renderer": "web",
        "features": [
            {"slug": "package-pricing-by-square-footage", "title": "Pricing", "attributes": {"basic_package_prices_by_square_footage": {"under_1200_sqft": "USD 390", "1201_2400_sqft": "USD 620", "2401_3600_sqft": "USD 860", "3600_plus_sqft": "USD 1120"}}},
            {"slug": "gallery-browsing-and-organization", "title": "Gallery", "attributes": {"main_gallery_tabs": ["photos", "floor_plans"], "interaction_mode": "interactive"}},
        ],
        "exercise": """
service = create_app().service
quote = service.quote(1800)
gallery = service.select_gallery('floor_plans')
print(json.dumps({'total': quote['total_usd'], 'selected': gallery['selected']}))
""",
    },
}


class WebRepositoryScaffoldTest(unittest.TestCase):
    def _materialize(self, root: Path, project_id: str, case: dict) -> None:
        (root / "src").mkdir(parents=True)
        (root / "scripts").mkdir()
        (root / "tests").mkdir()
        project = {
            "project_id": project_id,
            "title": "Test Project",
            "description": "Offline test",
            "renderer": case["renderer"],
            "primary_artifacts": [
                "dist/mobile-preview.html" if case["renderer"] == "mobile" else "dist/index.html",
                "dist/app-config.json" if case["renderer"] == "mobile" else "dist/catalog.json",
            ],
        }
        source = "PROJECT = " + repr(project) + "\nFEATURES = " + repr(case["features"]) + "\n"
        (root / "src" / "current_state.py").write_text(source, encoding="utf-8")
        artifacts = [
            "dist/mobile-preview.html" if case["renderer"] == "mobile" else "dist/index.html",
            "dist/app-config.json" if case["renderer"] == "mobile" else "dist/catalog.json",
        ]
        augment_web_repository(
            root,
            project_id,
            case["features"],
            {"renderer": case["renderer"], "primary_artifacts": artifacts},
        )

    def _run(self, root: Path, source: str) -> dict:
        program = "import json\nfrom application import create_app\n" + textwrap.dedent(source)
        result = subprocess.run(
            [sys.executable, "-c", program], cwd=root, text=True, encoding="utf-8",
            capture_output=True, check=False, env={"PYTHONPATH": str(root / "src")},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_project_specific_domain_behaviors(self):
        expected = {
            "42204309": lambda value: value["tickets"] == 4 and value["dashboard"]["commission_usd"] == 12,
            "43772711": lambda value: value["status"] == "provisioned" and value["workspace"]["theme"] == "dark",
            "43804272": lambda value: value == {"peak": 9.0, "direction": "rtl"},
            "44035087": lambda value: value == {"total": 620.0, "selected": "floor_plans"},
        }
        for project_id, case in PROJECT_CASES.items():
            with self.subTest(project_id=project_id), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self._materialize(root, project_id, case)
                self.assertTrue(expected[project_id](self._run(root, case["exercise"])))

    def test_build_outputs_interactive_ui_and_route_catalog(self):
        for project_id, case in PROJECT_CASES.items():
            with self.subTest(project_id=project_id), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self._materialize(root, project_id, case)
                value = self._run(root, """
from runtime import build, check
build('dist')
result = check('dist')
print(json.dumps(result))
""")
                self.assertGreater(value["route_count"], 0)
                page = "mobile-preview.html" if case["renderer"] == "mobile" else "index.html"
                html = (root / "dist" / page).read_text(encoding="utf-8")
                self.assertIn("app.js", html)
                self.assertIn("data-endpoint", html)
                contract = json.loads((root / "behavior_contract.json").read_text(encoding="utf-8"))
                self.assertEqual(contract["project_id"], project_id)
                self.assertTrue(contract["routes"])
                self.assertTrue(contract["actions"])
                self.assertNotIn("gold", json.dumps(contract).lower())

    def test_rejects_wrong_renderer_and_duplicate_slugs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "src" / "current_state.py").write_text("PROJECT={}\nFEATURES=[]\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "requires renderer"):
                augment_web_repository(root, "42204309", [], {"renderer": "mobile"})
            duplicated = [{"slug": "same"}, {"slug": "same"}]
            with self.assertRaisesRegex(ValueError, "unique"):
                augment_web_repository(root, "42204309", duplicated, {"renderer": "web"})

    def test_incomplete_snapshot_does_not_receive_future_domain_vocabulary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "src" / "current_state.py").write_text(
                "PROJECT={}\nFEATURES=[]\n", encoding="utf-8"
            )
            features = [
                {
                    "slug": "small-block-prize-mechanism",
                    "title": "Small block prize",
                    "attributes": {},
                }
            ]
            augment_web_repository(
                root,
                "42204309",
                features,
                {"renderer": "web", "primary_artifacts": ["dist/index.html"]},
            )
            domain = (root / "src" / "domain.py").read_text(encoding="utf-8")
            self.assertIn("CurrentPrizeService", domain)
            self.assertNotIn("register_referral", domain)
            self.assertNotIn("request_magic_link", domain)
            self.assertNotIn("/api/mints", domain)
            contract = json.loads(
                (root / "behavior_contract.json").read_text(encoding="utf-8")
            )
            self.assertEqual(contract["domain"], "current_prize_system")


if __name__ == "__main__":
    unittest.main()
