import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import test from "node:test"
import vm from "node:vm"
import { execFileSync } from "node:child_process"

const source = readFileSync(new URL("../Model.js", import.meta.url), "utf8")
const model = {}
vm.createContext(model)
vm.runInContext(source, model)

const catalog = JSON.parse(readFileSync(new URL("../companies.json", import.meta.url), "utf8"))
const manifest = JSON.parse(readFileSync(new URL("../manifest.json", import.meta.url), "utf8"))
const barWidget = readFileSync(new URL("../BarWidget.qml", import.meta.url), "utf8")
const panel = readFileSync(new URL("../Panel.qml", import.meta.url), "utf8")

test("shared policies agree across Python, QML and the manifest", () => {
  const limits = JSON.parse(execFileSync("python3", ["-c",
    "import json; from frontier_status import policy as p; print(json.dumps([p.MAX_INCIDENTS, p.MAX_OUTPUT_BYTES, p.FETCH_DEADLINE_SEC]))"
  ], {cwd: new URL("..", import.meta.url), encoding: "utf8"}))
  assert.equal(model.MAX_INCIDENTS, limits[0])
  assert.equal(model.MAX_OUTPUT_CHARS, limits[1]) // Helper JSON is ASCII, so bytes equal characters.
  assert.ok(model.FETCH_WATCHDOG_MS > limits[2] * 1000)
  const interval = manifest.barWidget.schema.find(field => field.key === "refreshIntervalSec")
  assert.equal(model.DEFAULT_REFRESH_SEC, interval.defaultValue)
  assert.equal(model.MIN_REFRESH_SEC, interval.min)
  assert.equal(model.MAX_REFRESH_SEC, interval.max)
})

test("remote incident lists are capped before creating UI rows", () => {
  const company = model.normalizeCompany({incidents: Array.from({length: 1000}, () => ({name: "incident"}))})
  assert.equal(company.incidents.length, 16)
})

test("remote markup remains literal and control characters are removed", () => {
  const markup = '<b>Outage</b><img src="https://example.test/tracker">'
  const parsed = model.parseReport(JSON.stringify({ok: true, companies: [{
    id: "openai", label: markup, error: "error\u001b\u202e!", incidents: [{name: markup + "\u0000\n"}]
  }]}), catalog)
  assert.equal(parsed.companies[0].label, markup)
  assert.equal(parsed.companies[0].incidents[0].name, markup)
  assert.equal(parsed.companies[0].error, "error  !")
  assert.equal(model.cleanText("x".repeat(1000), 180).length, 180)
  assert.equal(model.cleanText("障害が発生しました", 180), "障害が発生しました")
  assert.equal(model.heroMeta([], false, "error\u202e"), "error ")
})

test("provider name and remote status QML sinks explicitly render plain text", () => {
  const sinks = [...panel.matchAll(/Text\s*\{[^{}]*text:\s*modelData\.(?:name|error)[^{}]*\}/g)]
  assert.equal(sinks.length, 2)
  for (const [sink] of sinks) assert.match(sink, /textFormat:\s*Text\.PlainText/)
})

test("catalog json matches the loader", () => {
  const loaded = model.catalogFromJson(JSON.stringify(catalog))
  assert.equal(loaded.length, catalog.length)
  assert.equal(loaded.map((row) => row.id).join(","), catalog.map((row) => row.id).join(","))
})

test("manifest points at the bar entry and settings keys", () => {
  assert.equal(manifest.id, "io.github.ollieedgeley.ai-frontier-status")
  assert.deepEqual(manifest.kinds, ["bar-widget"])
  assert.equal(manifest.entryPoints.barWidget, "BarWidget.qml")
  assert.equal(manifest.preview, "preview.png")
  assert.equal(manifest.barWidget.defaults.refreshIntervalSec, 60)
  assert.equal(manifest.barWidget.defaults.enabledIds, "")
})

test("bar widget forwards panel lifecycle and uses the requested icon", () => {
  assert.match(barWidget, /^BarWidget\s*\{/m)
  for (const method of ["open", "close", "toggle", "closeForPopoutSwitch"])
    assert.match(barWidget, new RegExp(`function\\s+${method}\\s*\\(`))
  assert.match(barWidget, /text:\s*"󰠠"/)
  assert.match(barWidget, /active:\s*root\.alarming/)
})

test("panel persists one poll interval and company toggles", () => {
  assert.match(panel, /SettingsView/)
  assert.match(panel, /function\s+setCompanyEnabled/)
  assert.match(panel, /function\s+setRefreshInterval/)
  assert.match(panel, /enabledMapFromSettings/)
  assert.match(panel, /enabledFetchIds/)
  assert.match(panel, /anyUnavailable/)
  assert.match(panel, /python3/)
  assert.doesNotMatch(panel, /^\s*(readonly\s+)?property\s+\w+\s+enabledIds\b/m)
})

test("companies are off until listed in enabledIds", () => {
  const none = model.parseEnabledIds("", catalog)
  assert.equal(model.isEnabled("openai", none), false)
  const enabled = model.parseEnabledIds("openai,nope", catalog)
  assert.equal(model.isEnabled("openai", enabled), true)
  assert.equal(model.isEnabled("groq", enabled), false)
  assert.equal(enabled.nope, undefined)
  assert.equal(model.enabledIdList(enabled).join(","), "openai")
})

test("legacy all-off disabledIds stay off instead of flipping all on", () => {
  const allIds = catalog.map((row) => row.id).join(",")
  const fromLegacyOff = model.enabledMapFromSettings({ disabledIds: allIds }, catalog)
  assert.equal(model.enabledIdList(fromLegacyOff).join(","), "")
  assert.equal(model.isEnabled("openai", fromLegacyOff), false)
  assert.equal(model.enabledFetchIds(catalog, fromLegacyOff).join(","), "")
})

test("empty enabledIds is explicit none even if disabledIds still lists everyone", () => {
  const allIds = catalog.map((row) => row.id).join(",")
  const map = model.enabledMapFromSettings({ enabledIds: "", disabledIds: allIds }, catalog)
  assert.equal(model.enabledIdList(map).join(","), "")
  assert.equal(model.isEnabled("anthropic", map), false)
})

test("missing both keys means none enabled", () => {
  const map = model.enabledMapFromSettings({ refreshIntervalSec: 60 }, catalog)
  assert.equal(model.enabledIdList(map).join(","), "")
})

test("legacy partial disabledIds keep everyone else on", () => {
  const map = model.enabledMapFromSettings({ disabledIds: "openai" }, catalog)
  assert.equal(model.isEnabled("openai", map), false)
  assert.equal(model.isEnabled("anthropic", map), true)
})

test("turning the last company off persists an empty enabled list", () => {
  const next = model.withCompanyEnabled({ openai: true }, "openai", false)
  assert.equal(model.enabledIdList(next).join(","), "")
  const entry = model.widgetSettingsEntry("io.github.ollieedgeley.ai-frontier-status", next, 60)
  assert.equal(entry.enabledIds, "")
  assert.equal(entry.disabledIds, undefined)
  assert.equal(Object.keys(entry).sort().join(","), "enabledIds,id,refreshIntervalSec")
})

test("company filter matches name, id, and url", () => {
  const rows = model.filterCatalog(catalog, "cursor")
  assert.equal(rows.map((row) => row.id).join(","), "cursor")
  const byUrl = model.filterCatalog(catalog, "githubstatus")
  assert.equal(byUrl.map((row) => row.id).join(","), "copilot")
  assert.equal(model.filterCatalog(catalog, "   ").length, catalog.length)
  assert.equal(model.filterCatalog(catalog, "zz-no-such-vendor").length, 0)
})

test("refresh interval is clamped", () => {
  assert.equal(model.clampRefreshInterval(5, 60), 30)
  assert.equal(model.clampRefreshInterval(9000, 60), 3600)
  assert.equal(model.clampRefreshInterval("90", 60), 90)
  assert.equal(model.clampRefreshInterval("nope", 60), 60)
})

test("visible companies sort degraded first and fill waiting rows", () => {
  const visible = model.visibleCompanies(
    catalog.slice(0, 3),
    [
      { id: "openai", name: "OpenAI", degraded: false, label: "OK", indicator: "none" },
      { id: "anthropic", name: "Anthropic", degraded: true, label: "Degraded", indicator: "minor" }
    ],
    { openai: true, anthropic: true, google: true }
  )
  assert.equal(visible[0].id, "anthropic")
  assert.equal(visible[1].id, "google")
  assert.equal(visible[1].label, "Waiting for status")
  assert.equal(visible[2].id, "openai")
})

test("alarm tooltip names degraded companies", () => {
  const companies = [
    { name: "OpenAI", degraded: true },
    { name: "xAI", degraded: true }
  ]
  assert.equal(model.anyDegraded(companies), true)
  assert.equal(model.tooltipText(companies), "OpenAI and xAI are degraded")
  assert.equal(model.tooltipText([]), "Frontier AI status")
})

test("failed checks are never summarized as operational", () => {
  const companies = [
    { name: "OpenAI", degraded: false, error: "HTTP 503" },
    { name: "Anthropic", degraded: false, error: "" }
  ]
  assert.equal(model.anyUnavailable(companies), true)
  assert.equal(model.tooltipText(companies), "OpenAI status unavailable")
  assert.equal(model.heroMeta(companies, false, ""), "OpenAI status check unavailable")
})

test("degraded and unavailable checks are both included in summaries", () => {
  const companies = [
    { name: "OpenAI", degraded: true, error: "" },
    { name: "Anthropic", degraded: false, error: "Timed out" }
  ]
  assert.equal(model.tooltipText(companies), "OpenAI degraded; 1 check unavailable")
  assert.equal(
    model.heroMeta(companies, false, ""),
    "OpenAI is reporting a problem; 1 check unavailable"
  )
})

test("file urls become local paths", () => {
  assert.equal(model.fileUrlToPath("file:///home/ollie/plugin/fetch-status"), "/home/ollie/plugin/fetch-status")
})

test("report parser keeps catalog order for returned companies", () => {
  const parsed = model.parseReport(JSON.stringify({
    ok: true,
    fetchedAt: "2026-09-04T20:00:00Z",
    companies: [
      { id: "xai", name: "xAI", degraded: false, label: "OK", indicator: "none" },
      { id: "openai", name: "OpenAI", degraded: true, label: "Down", indicator: "major" }
    ]
  }), catalog)
  assert.equal(parsed.companies[0].id, "openai")
  assert.equal(parsed.companies[1].id, "xai")
  assert.equal(parsed.companies[0].degraded, true)
})
