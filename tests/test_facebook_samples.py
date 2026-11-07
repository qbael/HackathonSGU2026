import importlib.util
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("facebook_samples", ROOT / "scripts/import_facebook_samples.py")
samples = importlib.util.module_from_spec(spec)
spec.loader.exec_module(samples)


class FacebookSamplesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.source = self.folder / "source.json"
        (self.folder / "photo.jpg").write_bytes(b"\xff\xd8\xff\xe0real-photo-fixture")
        self.record = {"sourceId": "post-123", "sourceUrl": "https://www.facebook.com/groups/123/posts/456/",
                       "originalKind": "lost", "capturedAt": "2026-01-01T00:00:00+07:00",
                       "sourceText": "Mất tai nghe ở thư viện.", "title": "Tai nghe",
                       "publicDescription": "Tai nghe theo bài gốc.", "foundArea": "Thư viện",
                       "images": ["photo.jpg"]}
        self.write_source()

    def write_source(self):
        self.source.write_text(json.dumps(self.record, ensure_ascii=False), encoding="utf-8")

    def test_provenance_unknown_dates_real_assets_and_lost_conversion_disclosure(self):
        post = samples.load_dataset(self.folder)[0]
        content = post["payload"]["content"]
        self.assertEqual(content["title"], "Tai nghe")
        self.assertEqual(content["foundTimePrecision"], "unknown")
        self.assertIn("chưa xác nhận đã nhặt", content["publicDescription"])
        self.assertIn(self.record["sourceUrl"], content["publicDescription"])
        self.assertEqual(post["payload"]["custody"]["kind"], "external")
        self.assertNotIn("foundOn", content)
        self.record["foundDateVerified"] = True
        self.record["foundOn"] = "2026-01-01"
        self.write_source()
        with self.assertRaisesRegex(ValueError, "lost post"):
            samples.load_dataset(self.folder)
        self.record.update(originalKind="found", sourceUrl="https://timdo24h.vn/tim-thay-tai-nghe-123.html")
        self.write_source()
        self.assertEqual(samples.load_dataset(self.folder)[0]["payload"]["content"]["foundOn"], "2026-01-01")
        self.record["images"] = ["../outside.jpg"]
        self.write_source()
        with self.assertRaisesRegex(ValueError, "outside"):
            samples.load_dataset(self.folder)

    def test_scenarios_cover_all_custody_and_time_precisions_without_claiming_source_facts(self):
        times = [
            {"foundTimePrecision": "unknown"},
            {"foundTimePrecision": "date", "foundOn": "2026-01-01"},
            {"foundTimePrecision": "exact", "foundFrom": "2026-01-01T00:05:00+07:00"},
            {"foundTimePrecision": "range", "foundFrom": "2025-12-31T23:00:00+07:00",
             "foundUntil": "2026-01-01T01:00:00+07:00"},
        ]
        custodians = [
            {"kind": "person"},
            {"kind": "point", "pointId": "fd000000-0000-0000-0000-000000000002", "confirmedPhysicalReceipt": True},
            {"kind": "external", "name": "Quầy giả định", "address": "Địa chỉ local giả định"},
        ]
        for custody in custodians:
            for found in times:
                with self.subTest(custody=custody["kind"], precision=found["foundTimePrecision"]):
                    self.record["scenario"] = found | {"custody": custody}
                    self.write_source()
                    post = samples.prepare(self.source)
                    self.assertTrue(post["syntheticScenario"])
                    self.assertEqual(post["payload"]["custody"], custody)
                    self.assertEqual(post["payload"]["content"]["foundTimePrecision"], found["foundTimePrecision"])
                    self.assertIn("KỊCH BẢN GIẢ ĐỊNH", post["payload"]["content"]["publicDescription"])
                    self.assertIn(self.record["sourceUrl"], post["payload"]["content"]["publicDescription"])
                    self.assertEqual(json.loads(self.source.read_text())["originalKind"], "lost")

    def test_scenarios_export_canonical_values_for_dotnet_json(self):
        self.record["scenario"] = {"foundTimePrecision": "exact", "foundFrom": "2026-01-01 00:05:00+07:00",
                                   "custody": {"kind": "point", "pointId": "fd000000000000000000000000000002",
                                               "confirmedPhysicalReceipt": True}}
        self.write_source()
        post = samples.prepare(self.source)
        self.assertEqual(post["payload"]["content"]["foundFrom"], "2026-01-01T00:05:00+07:00")
        self.assertEqual(post["payload"]["custody"]["pointId"], "fd000000-0000-0000-0000-000000000002")
        self.assertEqual(self.record["scenario"]["custody"]["pointId"], "fd000000000000000000000000000002")
        self.record["scenario"] = {"foundTimePrecision": "date", "foundOn": "20260101", "custody": {"kind": "person"}}
        self.write_source()
        self.assertEqual(samples.prepare(self.source)["payload"]["content"]["foundOn"], "2026-01-01")

    def test_scenarios_reject_invalid_dates_custody_and_source_verification(self):
        invalid = [
            {"foundTimePrecision": "date", "foundOn": "2999-01-01"},
            {"foundTimePrecision": "unknown", "foundTimezone": "invalid-zone"},
            {"foundTimePrecision": "exact", "foundFrom": "2026-01-01T00:05:00"},
            {"foundTimePrecision": "range", "foundFrom": "2026-01-02T00:00:00+07:00",
             "foundUntil": "2026-01-01T00:00:00+07:00"},
            {"foundTimePrecision": "unknown", "foundOn": "2026-01-01"},
            {"foundTimePrecision": "unknown", "custody": {"kind": "point", "pointId": "not-a-uuid", "confirmedPhysicalReceipt": True}},
            {"foundTimePrecision": "unknown", "custody": {"kind": "point", "pointId": "fd000000-0000-0000-0000-000000000002"}},
            {"foundTimePrecision": "unknown", "custody": {"kind": "person", "name": "unexpected"}},
            {"foundTimePrecision": "unknown", "custody": {"kind": "external", "name": "Quầy"}},
        ]
        for scenario in invalid:
            with self.subTest(scenario=scenario):
                self.record["scenario"] = {"custody": {"kind": "person"}} | scenario
                self.write_source()
                with self.assertRaises(ValueError):
                    samples.prepare(self.source)
        self.record.update(originalKind="found", foundDateVerified=True, foundOn="2026-01-01",
                           scenario={"foundTimePrecision": "unknown", "custody": {"kind": "person"}})
        self.write_source()
        with self.assertRaisesRegex(ValueError, "cannot be marked as verified"):
            samples.prepare(self.source)

    def test_duplicate_source_ids_are_rejected(self):
        duplicate = self.folder / "duplicate"
        duplicate.mkdir()
        (duplicate / "source.json").write_text(self.source.read_text(), encoding="utf-8")
        (duplicate / "photo.jpg").write_bytes((self.folder / "photo.jpg").read_bytes())
        with self.assertRaisesRegex(ValueError, "duplicate sourceId"):
            samples.load_dataset(self.folder)

    def test_legacy_title_fingerprint_covers_exact_old_payload_and_all_source_changes(self):
        post = samples.prepare(self.source)
        legacy = post["payload"] | {"content": post["payload"]["content"] | {"title": "[Mẫu] Tai nghe"}}
        expected = hashlib.sha256(json.dumps({"source": self.record, "payload": legacy,
            "photos": [photo["sha256"] for photo in post["photos"]]}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        self.assertEqual(post["legacyTitleFingerprint"], expected)
        self.assertNotEqual(post["fingerprint"], expected)
        for field, value in (("title", "Ví"), ("sourceText", "Nội dung khác"), ("foundArea", "Khu vực khác")):
            with self.subTest(field=field):
                before = self.record[field]
                self.record[field] = value
                self.write_source()
                self.assertNotEqual(samples.prepare(self.source)["legacyTitleFingerprint"], expected)
                self.record[field] = before
        self.write_source()
        (self.folder / "photo.jpg").write_bytes(b"\xff\xd8\xffchanged-photo")
        self.assertNotEqual(samples.prepare(self.source)["legacyTitleFingerprint"], expected)

    @unittest.skipUnless(shutil.which("dotnet"), ".NET SDK is required for the local import guard check")
    def test_service_import_is_refused_in_production_before_reading_input_or_database(self):
        for mode in ([], ["--sync-titles"], ["--sync-source-urls"], ["--review-only"], ["--replace-masked"], ["--embed-originals"]):
            with self.subTest(mode=mode):
                result = subprocess.run(["dotnet", "run", "--project", str(ROOT / "apps/api"), "--no-restore", "--no-launch-profile", "--",
                                         "--import-public-samples", "nonexistent-prepared.json", "--actor-email", "existing@example.test", *mode],
                                        cwd=ROOT, env=os.environ | {"ASPNETCORE_ENVIRONMENT": "Production"},
                                        text=True, capture_output=True, timeout=60)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Source sample import is allowed only in Development", result.stderr)

    def test_prepare_json_exports_absolute_paths_without_changing_sources(self):
        before = self.source.read_bytes()
        prepared = self.folder / "prepared.json"
        result = subprocess.run([sys.executable, str(ROOT / "scripts/import_facebook_samples.py"), str(self.folder),
                                 "--prepare-json", str(prepared)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        posts = json.loads(prepared.read_text(encoding="utf-8"))
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["path"], str(self.source.resolve()))
        self.assertEqual(posts[0]["photos"][0]["path"], str((self.folder / "photo.jpg").resolve()))
        self.assertEqual(posts[0]["payload"]["content"]["title"], "Tai nghe")
        self.assertEqual(self.source.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
