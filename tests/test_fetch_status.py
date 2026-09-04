#!/usr/bin/env python3
import importlib.machinery
import importlib.util
import json
import unittest
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
