#!/usr/bin/env python3
import importlib.machinery
import importlib.util
import json
import io
import signal
import subprocess
import sys
import unittest
from email.message import Message
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_module():
    path = ROOT / "fetch-status"
    loader = importlib.machinery.SourceFileLoader("fetch_status", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


FS = load_module()


def row(company_id="openai"):
    return {
        "id": company_id,
        "name": company_id.title(),
        "url": "https://example.test",
        "kind": "statuspage",
        "endpoint": "https://example.test",
    }


def read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FetchStatusTests(unittest.TestCase):
    def test_nuxt_cycles_depth_and_expansion_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "cycle"):
            FS.deref_nuxt([[0]], 0)
        deep = [[index + 1] for index in range(40)] + ["leaf"]
        with self.assertRaisesRegex(ValueError, "complexity"):
            FS.deref_nuxt(deep, 0)
        repeated = [[index + 1, index + 1] for index in range(20)] + ["leaf"]
        with self.assertRaisesRegex(ValueError, "complexity"):
            FS.deref_nuxt(repeated, 0)
        # Booleans are values, not integer references into the table.
        self.assertIs(FS.deref_nuxt(["wrong", "also wrong"], True), True)

    def test_json_complexity_limits(self):
        cases = [
            json.dumps([0] * (FS.MAX_COLLECTION_ITEMS + 1)),
            json.dumps("x" * (FS.MAX_SOURCE_STRING + 1)),
            "[" * 40 + "0" + "]" * 40,
            json.dumps([[0] * 100 for _ in range(201)]),
        ]
        for body in cases:
            with self.subTest(length=len(body)), self.assertRaises(ValueError):
                FS.parse_json(body)

    def test_xml_rejects_entities_and_excessive_structure(self):
        cases = [
            '<!DOCTYPE rss [<!ENTITY x "expanded">]><rss>&x;</rss>',
            "<x>" * 40 + "</x>" * 40,
            "<rss>" + "<item/>" * (FS.MAX_COLLECTION_ITEMS + 1) + "</rss>",
        ]
        for body in cases:
            with self.subTest(length=len(body)), self.assertRaises(ValueError):
                FS.parse_xml(body)

    def test_display_limits_preserve_late_outage_classification(self):
        data = json.loads(read("statuspage-ok.json"))
        data["components"] = [{"name": "x" * 1000, "status": "operational"}] * 100
        data["components"].append({"name": "late outage", "status": "major_outage"})
        data["incidents"] = [{"name": "y" * 1000, "status": "investigating"}] * 100
        result = FS.parse_statuspage(json.dumps(data), row())
        self.assertTrue(result["degraded"])
        self.assertEqual(len(result["components"]), FS.MAX_COMPONENTS)
        self.assertEqual(len(result["incidents"]), FS.MAX_INCIDENTS)
        self.assertLessEqual(len(result["incidents"][0]["name"]), FS.MAX_FIELD_CHARS)

    def test_payload_over_limits_becomes_unknown_not_operational(self):
        data = json.loads(read("statuspage-ok.json"))
        data["components"] = [None] * (FS.MAX_COLLECTION_ITEMS + 1)
        with mock.patch.object(FS, "http_get", return_value=(json.dumps(data), "application/json")):
            result = FS.fetch_company(row())
        self.assertEqual(result["indicator"], "unknown")
        self.assertIn("limit", result["error"])

    def response(self, body, **headers):
        response = io.BytesIO(body)
        response.headers = Message()
        for key, value in headers.items():
            response.headers[key.replace("_", "-")] = str(value)
        return response

    def test_http_body_limit_with_absent_or_dishonest_length(self):
        for headers in ({}, {"Content_Length": 1}, {"Content_Length": 17}):
            with self.subTest(headers=headers), mock.patch.object(FS, "MAX_RESPONSE_BYTES", 16):
                response = self.response(b"x" * 17, **headers)
                with mock.patch.object(FS.urllib.request, "urlopen", return_value=response):
                    with self.assertRaisesRegex(ValueError, "byte limit"):
                        FS.http_get("https://example.test")

    def test_http_body_at_limit_and_compression_rejected(self):
        with mock.patch.object(FS, "MAX_RESPONSE_BYTES", 16):
            with mock.patch.object(FS.urllib.request, "urlopen", return_value=self.response(b"x" * 16)):
                self.assertEqual(FS.http_get("https://example.test")[0], "x" * 16)
        with mock.patch.object(FS.urllib.request, "urlopen", return_value=self.response(b"x", Content_Encoding="gzip")):
            with self.assertRaisesRegex(ValueError, "Compressed"):
                FS.http_get("https://example.test")

    def test_http_trickle_exceeds_elapsed_deadline(self):
        response = self.response(b"x")
        with mock.patch.object(FS.urllib.request, "urlopen", return_value=response), \
             mock.patch.object(FS.time, "monotonic", side_effect=[0, 1, 9]):
            with self.assertRaises(TimeoutError):
                FS.http_get("https://example.test", timeout=8)

    def test_output_limit_emits_no_partial_json(self):
        output = io.StringIO()
        with mock.patch.object(FS.sys, "stdout", output), mock.patch.object(FS, "MAX_OUTPUT_BYTES", 32):
            with self.assertRaisesRegex(ValueError, "output limit"):
                FS.write_report({"text": "x" * 33})
        self.assertEqual(output.getvalue(), "")

    def test_hard_deadline_kills_blocked_worker_threads(self):
        code = """
import runpy, sys, time
from concurrent.futures import ThreadPoolExecutor
module = runpy.run_path(sys.argv[1], run_name='deadline_test')
module['arm_deadline'](0.15)
with ThreadPoolExecutor() as pool:
    pool.submit(time.sleep, 30).result()
"""
        result = subprocess.run([sys.executable, "-c", code, str(ROOT / "fetch-status")],
                                capture_output=True, timeout=3)
        self.assertEqual(result.returncode, -signal.SIGALRM)
        self.assertEqual(result.stderr, b"")

    def test_catalog_ids_are_unique(self):
        catalog = FS.load_catalog()
        ids = [item["id"] for item in catalog]
        self.assertEqual(ids, sorted(set(ids), key=ids.index))
        self.assertIn("openai", ids)
        self.assertIn("anthropic", ids)
        self.assertIn("xai", ids)
        self.assertIn("copilot", ids)
        self.assertIn("cursor", ids)
        self.assertIn("huggingface", ids)
        self.assertIn("together", ids)
        self.assertIn("devin", ids)
        self.assertIn("midjourney", ids)

    def test_statuspage_operational(self):
        result = FS.parse_statuspage(read("statuspage-ok.json"), row())
        self.assertFalse(result["degraded"])
        self.assertEqual(result["indicator"], "none")
        self.assertEqual(result["label"], "All Systems Operational")
        names = [item["name"] for item in result["components"]]
        self.assertEqual(names, ["API"])

    def test_statuspage_component_filter_ignores_unrelated_github_outages(self):
        copilot = row("copilot")
        copilot["name"] = "GitHub Copilot"
        copilot["componentMatch"] = "copilot"
        result = FS.parse_statuspage(read("github-copilot.json"), copilot)
        self.assertTrue(result["degraded"])
        self.assertEqual(result["indicator"], "minor")
        names = [item["name"] for item in result["components"]]
        self.assertEqual(names, ["Copilot", "Copilot AI Model Providers"])
        self.assertEqual(
            [item["name"] for item in result["incidents"]],
            ["Incident with Grok Copilot AI Model Provider"],
        )
        self.assertEqual(result["label"], "Incident with Grok Copilot AI Model Provider")

        healthy = json.loads(read("github-copilot.json"))
        for item in healthy["components"]:
            item["status"] = "operational"
        healthy["incidents"] = [healthy["incidents"][0]]
        result = FS.parse_statuspage(json.dumps(healthy), copilot)
        self.assertFalse(result["degraded"])
        self.assertEqual(result["indicator"], "none")
        self.assertEqual(result["incidents"], [])
        self.assertEqual(result["label"], "All systems operational")

    def test_statuspage_degraded(self):
        result = FS.parse_statuspage(read("statuspage-degraded.json"), row())
        self.assertTrue(result["degraded"])
        self.assertEqual(result["indicator"], "minor")
        self.assertEqual(result["incidents"][0]["name"], "Elevated API errors")

    def test_betterstack_aggregate_state(self):
        ok = FS.parse_betterstack(read("betterstack-ok.json"), row("huggingface"))
        self.assertFalse(ok["degraded"])
        self.assertEqual(ok["indicator"], "none")
        down = FS.parse_betterstack(read("betterstack-down.json"), row("huggingface"))
        self.assertTrue(down["degraded"])
        self.assertEqual(down["indicator"], "critical")

    def test_instatus_up(self):
        result = FS.parse_instatus(read("instatus-up.json"), row("perplexity"))
        self.assertFalse(result["degraded"])
        self.assertEqual(result["indicator"], "none")

    def test_rss_open_and_resolved(self):
        open_result = FS.parse_rss(read("rss-open.xml"), row("xai"))
        self.assertTrue(open_result["degraded"])
        self.assertEqual(open_result["incidents"][0]["name"], "[API] Models outage")

        closed = FS.parse_rss(read("rss-resolved.xml"), row("xai"))
        self.assertFalse(closed["degraded"])
        self.assertEqual(closed["incidents"], [])

        openrouter = FS.parse_rss(read("rss-openrouter.xml"), row("openrouter"))
        self.assertTrue(openrouter["degraded"])
        self.assertEqual(
            [item["name"] for item in openrouter["incidents"]],
            ["Degraded video generation and batch jobs APIs"],
        )

    def test_google_filters_to_open_gemini_products(self):
        result = FS.parse_google_cloud(read("google-incidents.json"), row("google"))
        self.assertTrue(result["degraded"])
        self.assertEqual(result["incidents"][0]["name"], "Gemini API elevated latency")
        self.assertEqual(len(result["incidents"]), 1)

    def test_checkly_unresolved_incident(self):
        result = FS.parse_checkly(read("checkly-incident.html"), row("mistral"))
        self.assertTrue(result["degraded"])
        self.assertEqual(result["incidents"][0]["name"], "Free Tier Temporarily Disabled")
        self.assertEqual(result["indicator"], "major")

    def test_checkly_operational(self):
        result = FS.parse_checkly(read("checkly-ok.html"), row("mistral"))
        self.assertFalse(result["degraded"])
        self.assertEqual(result["indicator"], "none")

    def test_deepinfra_ignores_single_model_blips(self):
        ok = FS.parse_deepinfra(read("deepinfra-ok.json"), row("deepinfra"))
        self.assertFalse(ok["degraded"])
        self.assertEqual([item["name"] for item in ok["components"]], ["API", "Website"])
        bad = FS.parse_deepinfra(read("deepinfra-bad.json"), row("deepinfra"))
        self.assertTrue(bad["degraded"])
        self.assertEqual(bad["incidents"][0]["name"], "API latency elevated")

    def test_midjourney_overall_status(self):
        ok = FS.parse_midjourney(read("midjourney-ok.json"), row("midjourney"))
        self.assertFalse(ok["degraded"])
        self.assertEqual(ok["indicator"], "none")
        self.assertEqual(ok["label"], "You can create images right now.")
        bad = FS.parse_midjourney(read("midjourney-bad.json"), row("midjourney"))
        self.assertTrue(bad["degraded"])
        self.assertEqual(bad["indicator"], "major")
        self.assertEqual(bad["incidents"][0]["name"], "You cannot create images right now.")

    def test_deepseek_headings(self):
        ok = FS.parse_deepseek(read("deepseek-ok.html"), row("deepseek"))
        self.assertFalse(ok["degraded"])
        bad = FS.parse_deepseek(read("deepseek-bad.html"), row("deepseek"))
        self.assertTrue(bad["degraded"])
        self.assertEqual(bad["label"], "Degraded Performance")

    def test_selected_rows_keep_catalog_order(self):
        catalog = FS.load_catalog()
        rows = FS.selected_rows(catalog, ["xai", "openai"])
        self.assertEqual([item["id"] for item in rows], ["openai", "xai"])

    def test_unrecognized_payloads_raise_instead_of_reporting_operational(self):
        cases = [
            ("statuspage", FS.parse_statuspage, "{}"),
            ("instatus", FS.parse_instatus, "{}"),
            ("betterstack", FS.parse_betterstack, "{}"),
            ("google-cloud", FS.parse_google_cloud, "{}"),
            ("rss", FS.parse_rss, "<rss><channel/></rss>"),
            ("checkly", FS.parse_checkly, "<html></html>"),
            ("midjourney", FS.parse_midjourney, "{}"),
            ("deepinfra", FS.parse_deepinfra, "{}"),
        ]
        for kind, parser, body in cases:
            with self.subTest(kind=kind):
                with self.assertRaises(ValueError):
                    parser(body, {**row(kind), "kind": kind})

    def test_fetch_company_turns_an_invalid_payload_into_an_error(self):
        with mock.patch.object(FS, "http_get", return_value=("{}", "application/json")):
            result = FS.fetch_company(row())
        self.assertFalse(result["degraded"])
        self.assertEqual(result["indicator"], "unknown")
        self.assertIn("no status indicator", result["error"])


if __name__ == "__main__":
    unittest.main()
