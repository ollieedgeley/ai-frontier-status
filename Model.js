/**
 * Pure view-model helpers shared by the panel and settings view.
 * @typedef {{id:string, name:string, url:string, kind:string, endpoint:string}} CatalogEntry
 * @typedef {{name:string, status:string}} Incident
 * @typedef {{id:string, name:string, url:string, indicator:string, label:string,
 *   degraded:boolean, error:string, incidents:Incident[]}} CompanyResult
 * @typedef {{ok:boolean, fetchedAt:string, companies:CompanyResult[], error:string}} Report
 */

var DEFAULT_REFRESH_SEC = 60
var MIN_REFRESH_SEC = 30
var MAX_REFRESH_SEC = 3600
var MAX_INCIDENTS = 16
var MAX_ID_CHARS = 40
var MAX_STATUS_CHARS = 40
var MAX_TIMESTAMP_CHARS = 40
var MAX_NAME_CHARS = 80
var MAX_LABEL_CHARS = 180
var MAX_MODULE_ID_CHARS = 180
var MAX_ERROR_CHARS = 200
var MAX_URL_CHARS = 300
// The watchdog allows the helper's 60-second kernel deadline time to exit.
var FETCH_WATCHDOG_MS = 65 * 1000
var CATALOG_WATCHDOG_MS = 5 * 1000
var MAX_OUTPUT_CHARS = 512 * 1024
var MAX_ERROR_OUTPUT_CHARS = 4 * 1024

/** Replace display controls before truncation; preserve ordinary Unicode and literal markup. */
function cleanText(value, maxLength) {
  var text = String(value == null ? "" : value)
  // Bidirectional overrides and terminal controls can disguise provider messages.
  text = text.replace(/[\u0000-\u001f\u007f-\u009f\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]/g, " ")
  if (maxLength && text.length > maxLength) return text.slice(0, maxLength)
  return text
}

function asObject(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {}
}

function asArray(value) {
  if (Array.isArray(value)) return value
  if (value && typeof value === "object" && typeof value.length === "number") {
    var out = []
    for (var i = 0; i < value.length; i++) out.push(value[i])
    return out
  }
  return []
}

function catalogFromJson(raw) {
  try {
    var data = typeof raw === "string" ? JSON.parse(raw) : raw
    var rows = Array.isArray(data) ? data : asArray(data && data.companies)
    var out = []
    for (var i = 0; i < rows.length; i++) {
      var row = asObject(rows[i])
      var id = cleanText(row.id, MAX_ID_CHARS).trim()
      var name = cleanText(row.name, MAX_NAME_CHARS).trim()
      if (!id || !name) continue
      out.push({
        id: id,
        name: name,
        url: cleanText(row.url, MAX_URL_CHARS).trim(),
        kind: cleanText(row.kind, MAX_ID_CHARS).trim(),
        endpoint: cleanText(row.endpoint, MAX_URL_CHARS).trim()
      })
    }
    return out
  } catch (e) {
    return []
  }
}

function hasSetting(settings, key) {
  var current = asObject(settings)
  var value = current[key]
  return value !== undefined && value !== null
}

function parseEnabledIds(raw, catalog) {
  var enabled = {}
  var items = []
  if (typeof raw === "string") {
    items = raw.split(",")
  } else {
    items = asArray(raw)
  }
  for (var i = 0; i < items.length; i++) {
    var id = cleanText(items[i], MAX_ID_CHARS).trim()
    if (id) enabled[id] = true
  }
  if (catalog && catalog.length) {
    var known = {}
    for (var c = 0; c < catalog.length; c++) known[catalog[c].id] = true
    for (var key in enabled) {
      if (!known[key]) delete enabled[key]
    }
  }
  return enabled
}

function enabledMapFromLegacyDisabled(raw, catalog) {
  var disabled = parseEnabledIds(raw, catalog)
  var rows = asArray(catalog)
  var enabled = {}
  for (var i = 0; i < rows.length; i++) {
    var id = rows[i] && rows[i].id
    if (id && disabled[id] !== true) enabled[id] = true
  }
  return enabled
}

/** Explicit enabledIds wins; legacy disabledIds is migrated only when it is absent. */
function enabledMapFromSettings(settings, catalog) {
  var current = asObject(settings)
  if (hasSetting(current, "enabledIds")) return parseEnabledIds(current.enabledIds, catalog)
  if (hasSetting(current, "disabledIds")) return enabledMapFromLegacyDisabled(current.disabledIds, catalog)
  return {}
}

function enabledIdList(enabled) {
  var map = asObject(enabled)
  var ids = []
  for (var id in map) {
    if (map[id]) ids.push(id)
  }
  ids.sort()
  return ids
}

function withCompanyEnabled(enabled, id, on) {
  var next = {}
  var ids = enabledIdList(enabled)
  for (var i = 0; i < ids.length; i++) next[ids[i]] = true
  var companyId = cleanText(id, MAX_ID_CHARS).trim()
  if (!companyId) return next
  if (on) next[companyId] = true
  else delete next[companyId]
  return next
}

function widgetSettingsEntry(moduleName, enabled, refreshIntervalSec) {
  var moduleId = cleanText(moduleName, MAX_MODULE_ID_CHARS).trim()
  if (moduleId === "") return null
  var ids = typeof enabled === "string" ? enabled : enabledIdList(enabled).join(",")
  return {
    id: moduleId,
    enabledIds: ids,
    refreshIntervalSec: clampRefreshInterval(refreshIntervalSec, DEFAULT_REFRESH_SEC)
  }
}

function isEnabled(id, enabled) {
  return asObject(enabled)[id] === true
}

function enabledCompanies(catalog, enabled) {
  var rows = asArray(catalog)
  var out = []
  for (var i = 0; i < rows.length; i++) {
    if (isEnabled(rows[i].id, enabled)) out.push(rows[i])
  }
  return out
}

function enabledFetchIds(catalog, enabled) {
  var rows = enabledCompanies(catalog, enabled)
  var ids = []
  for (var i = 0; i < rows.length; i++) ids.push(rows[i].id)
  return ids
}

function filterCatalog(catalog, query) {
  var rows = asArray(catalog)
  var needle = String(query || "").replace(/^\s+|\s+$/g, "").toLowerCase()
  if (!needle) return rows
  var out = []
  for (var i = 0; i < rows.length; i++) {
    var row = rows[i] || {}
    var hay = [row.name, row.id, row.url].join(" ").toLowerCase()
    if (hay.indexOf(needle) >= 0) out.push(row)
  }
  return out
}

function clampRefreshInterval(value, fallback) {
  var n = parseInt(value, 10)
  if (isNaN(n)) n = fallback == null ? DEFAULT_REFRESH_SEC : fallback
  if (n < MIN_REFRESH_SEC) return MIN_REFRESH_SEC
  if (n > MAX_REFRESH_SEC) return MAX_REFRESH_SEC
  return n
}

/**
 * Normalize helper output and keep catalog ordering. Malformed JSON returns ok:false.
 * Individual provider errors remain company results, not whole-report failures.
 * @param {string|Object} raw
 * @param {CatalogEntry[]} catalog
 * @returns {Report}
 */
function parseReport(raw, catalog) {
  var empty = { ok: false, fetchedAt: "", companies: [], error: "" }
  try {
    var data = typeof raw === "string" ? JSON.parse(String(raw || "").trim() || "{}") : raw
    if (!data || typeof data !== "object") return empty
    var byId = {}
    var rows = asArray(data.companies)
    for (var i = 0; i < rows.length; i++) {
      var row = normalizeCompany(rows[i])
      if (row.id) byId[row.id] = row
    }
    var companies = []
    var source = catalog && catalog.length ? catalog : rows
    for (var c = 0; c < source.length; c++) {
      var id = source[c].id || normalizeCompany(source[c]).id
      if (byId[id]) companies.push(byId[id])
    }
    return {
      ok: data.ok !== false,
      fetchedAt: cleanText(data.fetchedAt, MAX_TIMESTAMP_CHARS),
      companies: companies,
      error: cleanText(data.error, MAX_ERROR_CHARS)
    }
  } catch (e) {
    empty.error = "Could not parse status report"
    return empty
  }
}

/**
 * Bound display fields and incidents; QML must still render them as plain text.
 * @param {Object} row
 * @returns {CompanyResult}
 */
function normalizeCompany(row) {
  var item = asObject(row)
  var indicator = cleanText(item.indicator, MAX_STATUS_CHARS).trim().toLowerCase() || "unknown"
  var incidents = []
  var rawIncidents = asArray(item.incidents)
  for (var i = 0; i < Math.min(rawIncidents.length, MAX_INCIDENTS); i++) {
    var incident = asObject(rawIncidents[i])
    var name = cleanText(incident.name, MAX_LABEL_CHARS).trim()
    if (!name) continue
    incidents.push({
      name: name,
      status: cleanText(incident.status, MAX_STATUS_CHARS).trim().toLowerCase()
    })
  }
  return {
    id: cleanText(item.id, MAX_ID_CHARS).trim(),
    name: cleanText(item.name, MAX_NAME_CHARS).trim(),
    url: cleanText(item.url, MAX_URL_CHARS).trim(),
    indicator: indicator,
    label: cleanText(item.label, MAX_LABEL_CHARS).trim() || "Status unknown",
    degraded: item.degraded === true,
    error: cleanText(item.error, MAX_ERROR_CHARS).trim(),
    incidents: incidents
  }
}

function visibleCompanies(catalog, reportCompanies, enabledMap) {
  var enabled = enabledCompanies(catalog, enabledMap)
  var byId = {}
  var rows = asArray(reportCompanies)
  for (var i = 0; i < rows.length; i++) byId[rows[i].id] = rows[i]
  var out = []
  for (var e = 0; e < enabled.length; e++) {
    var company = enabled[e]
    out.push(byId[company.id] || {
      id: company.id,
      name: company.name,
      url: company.url,
      indicator: "unknown",
      label: "Waiting for status",
      degraded: false,
      error: "",
      incidents: []
    })
  }
  out.sort(function(a, b) {
    if (a.degraded !== b.degraded) return a.degraded ? -1 : 1
    if (!!a.error !== !!b.error) return a.error ? -1 : 1
    return String(a.name).localeCompare(String(b.name))
  })
  return out
}

function anyDegraded(companies) {
  var rows = asArray(companies)
  for (var i = 0; i < rows.length; i++) {
    if (rows[i] && rows[i].degraded) return true
  }
  return false
}

function degradedNames(companies) {
  var rows = asArray(companies)
  var names = []
  for (var i = 0; i < rows.length; i++) {
    if (rows[i] && rows[i].degraded) names.push(rows[i].name)
  }
  return names
}

function unavailableNames(companies) {
  var rows = asArray(companies)
  var names = []
  for (var i = 0; i < rows.length; i++) {
    if (rows[i] && rows[i].error) names.push(rows[i].name)
  }
  return names
}

function anyUnavailable(companies) {
  return unavailableNames(companies).length > 0
}

function tooltipText(companies) {
  var names = degradedNames(companies)
  var unavailable = unavailableNames(companies)
  if (names.length > 0 && unavailable.length > 0) {
    var degraded = names.length === 1 ? names[0] + " degraded" : names.length + " companies degraded"
    return degraded + "; " + unavailable.length + (unavailable.length === 1
      ? " check unavailable" : " checks unavailable")
  }
  if (names.length === 1) return names[0] + " is degraded"
  if (names.length === 2) return names[0] + " and " + names[1] + " are degraded"
  if (names.length > 2) return names.length + " companies are degraded"
  if (unavailable.length === 1) return unavailable[0] + " status unavailable"
  if (unavailable.length > 1) return unavailable.length + " status checks unavailable"
  return "Frontier AI status"
}

function heroMeta(companies, loading, errorText) {
  if (errorText) return cleanText(errorText, MAX_ERROR_CHARS)
  if (loading) return "Checking status pages"
  var names = degradedNames(companies)
  var unavailable = unavailableNames(companies)
  var unavailableSuffix = unavailable.length > 0
    ? "; " + unavailable.length + (unavailable.length === 1
      ? " check unavailable" : " checks unavailable")
    : ""
  if (names.length === 1) return names[0] + " is reporting a problem" + unavailableSuffix
  if (names.length > 1) return names.length + " companies are reporting problems" + unavailableSuffix
  if (unavailable.length === 1) return unavailable[0] + " status check unavailable"
  if (unavailable.length > 1) return unavailable.length + " status checks unavailable"
  if (!companies || companies.length === 0) return "No companies enabled"
  return "All selected companies operational"
}

function fileUrlToPath(url) {
  var text = String(url || "").replace(/^file:\/\//, "")
  try {
    return decodeURIComponent(text)
  } catch (e) {
    return text
  }
}
