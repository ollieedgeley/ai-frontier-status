"""Validate provider payloads and construct bounded, normalized status results."""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import Any, NotRequired, TypedDict
from xml.etree import ElementTree as ET

from .policy import (
    MAX_RESPONSE_BYTES, MAX_PARSE_NODES, MAX_PARSE_DEPTH, MAX_COLLECTION_ITEMS,
    MAX_SOURCE_STRING, MAX_INCIDENTS, MAX_COMPONENTS, MAX_FIELD_CHARS,
    XML_READ_CHUNK_CHARS, MAX_STATUS_HEADINGS,
)

class CatalogEntry(TypedDict):
    """Reviewed provider identity, endpoint and optional component filter."""

    id: str
    name: str
    url: str
    kind: str
    endpoint: str
    componentMatch: NotRequired[str]


class StatusDetail(TypedDict):
    """Display detail; severity is only supplied by some providers."""

    name: str
    status: str
    severity: NotRequired[str]


class CompanyResult(TypedDict):
    """Provider result. Errors use unknown status, never operational success."""

    id: str
    name: str
    url: str
    indicator: str
    label: str
    degraded: bool
    error: str
    incidents: list[StatusDetail]
    components: list[StatusDetail]


class StatusReport(TypedDict):
    """Fetch completion envelope; individual companies may still carry errors."""

    ok: bool
    fetchedAt: str
    companies: list[CompanyResult]


GOOGLE_PRODUCT_RE = re.compile(
    r"gemini|vertex ai|imagen|veo|deepmind|google ai studio|generative language",
    re.I,
)
DEGRADED_COMPONENT = {
    "degraded_performance",
    "partial_outage",
    "major_outage",
    "minor_outage",
}
INSTATUS_OK = {"UP"}
BETTERSTACK_OK = {"operational"}
RSS_RESOLVED_RE = re.compile(r"status:\s*resolved", re.I)
RSS_STATUS_RE = re.compile(
    r"(?:status:\s*)?(investigating|identified|monitoring|resolved|completed|postmortem)\b",
    re.I,
)
DEEPINFRA_OK = {"OPERATIONAL"}
DEEPSEEK_OK_RE = re.compile(
    r"everything is running smoothly|all systems are operating as expected|all systems operational",
    re.I,
)
DEEPSEEK_BAD_RE = re.compile(
    r"degraded performance|partial outage|major outage|partially unavailable|部分中断|性能下降",
    re.I,
)


def checked_body(body: str) -> str:
    if len(body) > MAX_RESPONSE_BYTES or len(body.encode("utf-8")) > MAX_RESPONSE_BYTES:
        raise ValueError("Status response exceeds byte limit")
    return body


def parse_json(body: str) -> Any:
    """Decode JSON and reject excessive structure before provider interpretation."""
    data = json.loads(checked_body(body))
    stack = [(data, 0)]
    nodes = 0
    while stack:
        value, depth = stack.pop()
        nodes += 1
        if nodes > MAX_PARSE_NODES or depth > MAX_PARSE_DEPTH:
            raise ValueError("Status payload exceeds complexity limit")
        if isinstance(value, str) and len(value) > MAX_SOURCE_STRING:
            raise ValueError("Status payload string exceeds limit")
        if isinstance(value, (dict, list)):
            if len(value) > MAX_COLLECTION_ITEMS:
                raise ValueError("Status payload collection exceeds limit")
            if isinstance(value, dict):
                if any(len(key) > MAX_SOURCE_STRING for key in value):
                    raise ValueError("Status payload key exceeds limit")
                values = value.values()
            else:
                values = value
            stack.extend((item, depth + 1) for item in values)
    return data


def parse_xml(body: str) -> ET.Element:
    checked_body(body)
    # Status feeds need no DTD or entities. Reject them before XML expansion.
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)", body, re.I):
        raise ValueError("XML declarations are not supported")
    parser = ET.XMLPullParser(events=("start", "end"))
    depth = nodes = 0
    root = None
    for offset in range(0, len(body), XML_READ_CHUNK_CHARS):
        parser.feed(body[offset:offset + XML_READ_CHUNK_CHARS])
        for event, element in parser.read_events():
            if event == "start":
                if root is None:
                    root = element
                depth += 1
                nodes += 1
                if depth > MAX_PARSE_DEPTH or nodes > MAX_PARSE_NODES:
                    raise ValueError("RSS payload exceeds complexity limit")
            else:
                if len(element) > MAX_COLLECTION_ITEMS or any(
                    len(text or "") > MAX_SOURCE_STRING for text in (element.text, element.tail)
                ):
                    raise ValueError("RSS payload exceeds collection or string limit")
                depth -= 1
    parser.close()
    if root is None:
        raise ValueError("RSS payload is empty")
    return root


def build_company_result(row: CatalogEntry, **overrides: Any) -> CompanyResult:
    """Build a result and cap display details after full status classification."""
    result: CompanyResult = {
        "id": row["id"],
        "name": row["name"],
        "url": row["url"],
        "indicator": "unknown",
        "label": "Status unknown",
        "degraded": False,
        "error": "",
        "incidents": [],
        "components": [],
    }
    result.update(overrides)
    # Classification uses the full validated input; only display details are truncated.
    for key in ("id", "name", "url", "indicator", "label", "error"):
        result[key] = str(result[key])[:MAX_FIELD_CHARS]
    for key, limit in (("incidents", MAX_INCIDENTS), ("components", MAX_COMPONENTS)):
        result[key] = [
            {field: str(item[field])[:MAX_FIELD_CHARS]
             for field in ("name", "status", "severity") if field in item}
            for item in result[key][:limit]
        ]
    return result


def indicator_from_statuspage(value: str) -> str:
    text = (value or "none").strip().lower()
    if text in {"none", "minor", "major", "critical", "maintenance"}:
        return "none" if text == "none" else text
    return "minor"


def component_match_re(row: CatalogEntry) -> re.Pattern[str] | None:
    raw = str(row.get("componentMatch") or "").strip()
    if not raw:
        return None
    return re.compile(raw, re.I)


def name_matches(name: str, pattern: re.Pattern[str] | None) -> bool:
    if pattern is None:
        return True
    return bool(pattern.search(name or ""))


def indicator_from_components(components: list[dict[str, str]], incidents: list[dict[str, str]]) -> str:
    rank = {"none": 0, "maintenance": 1, "minor": 2, "major": 3, "critical": 4}
    worst = "none"
    for item in components:
        state = item.get("status") or ""
        if state == "major_outage":
            candidate = "critical"
        elif state == "partial_outage":
            candidate = "major"
        elif state in DEGRADED_COMPONENT:
            candidate = "minor"
        elif state == "under_maintenance":
            candidate = "maintenance"
        else:
            continue
        if rank[candidate] > rank[worst]:
            worst = candidate
    if incidents and worst in {"none", "maintenance"}:
        worst = "minor"
    return worst


def incident_matches(item: dict[str, Any], pattern: re.Pattern[str] | None) -> bool:
    if pattern is None:
        return True
    for component in item.get("components") or []:
        if isinstance(component, dict) and name_matches(str(component.get("name") or ""), pattern):
            return True
    return name_matches(str(item.get("name") or ""), pattern)


def label_for(indicator: str, description: str, degraded: bool) -> str:
    text = (description or "").strip()
    if text:
        return text
    if indicator == "maintenance":
        return "Under maintenance"
    if indicator == "critical":
        return "Major outage"
    if indicator == "major":
        return "Partial outage"
    if indicator == "minor" or degraded:
        return "Degraded performance"
    if indicator == "none":
        return "All systems operational"
    return "Status unknown"


def parse_statuspage(body: str, row: CatalogEntry) -> CompanyResult:
    data = parse_json(body)
    if not isinstance(data, dict):
        raise ValueError("Statuspage payload is not an object")
    status = data.get("status")
    if not isinstance(status, dict) or not isinstance(status.get("indicator"), str):
        raise ValueError("Statuspage payload has no status indicator")
    if not isinstance(data.get("components"), list):
        raise ValueError("Statuspage payload has no component list")
    pattern = component_match_re(row)
    components = []
    for item in data.get("components") or []:
        if not isinstance(item, dict) or item.get("group"):
            continue
        name = str(item.get("name") or "").strip()
        state = str(item.get("status") or "").strip().lower()
        if not name or not name_matches(name, pattern):
            continue
        components.append({"name": name, "status": state or "operational"})
    incidents = []
    for item in data.get("incidents") or []:
        if not isinstance(item, dict):
            continue
        state = str(item.get("status") or "").strip().lower()
        if state in {"resolved", "postmortem", ""}:
            continue
        name = str(item.get("name") or "").strip()
        if not name or not incident_matches(item, pattern):
            continue
        incidents.append({"name": name, "status": state})
    component_hit = any(item["status"] in DEGRADED_COMPONENT for item in components)
    if pattern is not None:
        indicator = indicator_from_components(components, incidents)
        degraded = component_hit or bool(incidents)
        description = incidents[0]["name"] if incidents else ""
    else:
        indicator = indicator_from_statuspage(str(status.get("indicator") or "none"))
        degraded = indicator != "none" or component_hit or bool(incidents)
        if degraded and indicator == "none":
            indicator = "minor"
        description = str(status.get("description") or "")
    return build_company_result(
        row,
        indicator=indicator,
        label=label_for(indicator, description, degraded),
        degraded=degraded,
        incidents=incidents,
        components=components,
    )


def parse_instatus(body: str, row: CatalogEntry) -> CompanyResult:
    data = parse_json(body)
    if not isinstance(data, dict):
        raise ValueError("Instatus payload is not an object")
    page = data.get("page")
    if not isinstance(page, dict) or not isinstance(page.get("status"), str):
        raise ValueError("Instatus payload has no page status")
    status = str(page["status"]).strip().upper()
    if not status:
        raise ValueError("Instatus page status is empty")
    incidents = []
    for item in data.get("activeIncidents") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        state = str(item.get("status") or "").strip().lower()
        if name:
            incidents.append({"name": name, "status": state})
    degraded = status not in INSTATUS_OK or bool(incidents)
    if status == "UNDERMAINTENANCE":
        indicator = "maintenance"
    elif status in {"ALLMAJOROUTAGE", "SOMEMAJOROUTAGE", "ONEMAJOROUTAGE"}:
        indicator = "critical"
    elif degraded:
        indicator = "minor"
    else:
        indicator = "none"
    return build_company_result(
        row,
        indicator=indicator,
        label=label_for(indicator, "All systems operational" if not degraded else "", degraded),
        degraded=degraded,
        incidents=incidents,
    )


def parse_betterstack(body: str, row: CatalogEntry) -> CompanyResult:
    data = parse_json(body)
    if not isinstance(data, dict):
        raise ValueError("Better Stack payload is not an object")
    resource = data.get("data")
    attrs = resource.get("attributes") if isinstance(resource, dict) else None
    if not isinstance(attrs, dict) or not isinstance(attrs.get("aggregate_state"), str):
        raise ValueError("Better Stack payload has no aggregate state")
    state = str(attrs["aggregate_state"]).strip().lower()
    if not state:
        raise ValueError("Better Stack aggregate state is empty")
    degraded = state not in BETTERSTACK_OK
    if state in {"downtime", "major_outage"}:
        indicator = "critical"
    elif state == "maintenance":
        indicator = "maintenance"
    elif degraded:
        indicator = "minor"
    else:
        indicator = "none"
    return build_company_result(
        row,
        indicator=indicator,
        label=label_for(indicator, state.replace("_", " ").capitalize(), degraded),
        degraded=degraded,
    )


def google_product_hit(incident: dict[str, Any]) -> bool:
    titles = []
    for product in incident.get("affected_products") or []:
        if isinstance(product, dict):
            titles.append(str(product.get("title") or product.get("current_title") or ""))
        else:
            titles.append(str(product))
    blob = " ".join(titles) + " " + str(incident.get("external_desc") or "")
    return bool(GOOGLE_PRODUCT_RE.search(blob))


def parse_google_cloud(body: str, row: CatalogEntry) -> CompanyResult:
    data = parse_json(body)
    if not isinstance(data, list):
        raise ValueError("Google incidents payload is not a list")
    incidents = []
    worst = "none"
    for item in data:
        if not isinstance(item, dict) or item.get("end") or not google_product_hit(item):
            continue
        name = str(item.get("external_desc") or "").strip()
        impact = str(item.get("status_impact") or item.get("severity") or "").strip().lower()
        if impact in {"critical", "high"}:
            worst = "critical"
        elif impact in {"medium", "low"} and worst == "none":
            worst = "minor"
        elif worst == "none":
            worst = "minor"
        if name:
            incidents.append({"name": name, "status": "ongoing"})
    degraded = bool(incidents)
    indicator = worst if degraded else "none"
    return build_company_result(
        row,
        indicator=indicator,
        label=label_for(
            indicator,
            incidents[0]["name"] if incidents else "Gemini products operational",
            degraded,
        ),
        degraded=degraded,
        incidents=incidents,
    )


def rss_text(node: ET.Element | None) -> str:
    if node is None or node.text is None:
        return ""
    return str(node.text)


def rss_item_resolved(description: str, categories: list[str]) -> bool:
    if any(cat in {"resolved", "completed"} for cat in categories):
        return True
    match = RSS_STATUS_RE.search(description or "")
    if not match:
        return bool(RSS_RESOLVED_RE.search(description or ""))
    return match.group(1).lower() in {"resolved", "completed", "postmortem"}


def parse_rss(body: str, row: CatalogEntry) -> CompanyResult:
    root = parse_xml(body)
    channel = root.find("./channel")
    if root.tag != "rss" or channel is None or not rss_text(channel.find("title")).strip():
        raise ValueError("RSS payload has no titled channel")
    incidents = []
    for item in root.findall("./channel/item"):
        title = rss_text(item.find("title")).strip()
        description = rss_text(item.find("description"))
        categories = [
            (child.text or "").strip().lower()
            for child in item.findall("category")
            if child.text
        ]
        resolved = rss_item_resolved(description, categories)
        if resolved or not title:
            continue
        incidents.append({"name": title, "status": "ongoing"})
    degraded = bool(incidents)
    indicator = "minor" if degraded else "none"
    return build_company_result(
        row,
        indicator=indicator,
        label=label_for(
            indicator,
            incidents[0]["name"] if incidents else "All systems operational",
            degraded,
        ),
        degraded=degraded,
        incidents=incidents,
    )


def extract_nuxt_data(html: str) -> list[Any] | None:
    checked_body(html)
    match = re.search(r'id="__NUXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not match:
        return None
    data = parse_json(match.group(1))
    return data if isinstance(data, list) else None


def deref_nuxt(data: list[Any], value: Any, budget: list[int] | None = None,
               active: set[int] | None = None, depth: int = 0) -> Any:
    """Expand Checkly incident references within a caller-shared work budget.

    The one-element budget is mutated across all roots in a page, so repeated
    references cannot each receive a fresh allowance. Active indexes detect
    cycles on the current path. Only known incident containers are expanded;
    scalar integers in the table remain values rather than further references.
    Invalid cycles or excessive work/depth raise ValueError.
    """
    budget = [MAX_PARSE_NODES] if budget is None else budget
    active = set() if active is None else active
    budget[0] -= 1
    if budget[0] < 0 or depth > MAX_PARSE_DEPTH:
        raise ValueError("Nuxt expansion exceeds complexity limit")
    if type(value) is int and 0 <= value < len(data):
        if value in active:
            raise ValueError("Nuxt reference cycle")
        target = data[value]
        if isinstance(target, (str, bool)) or target is None:
            return target
        if isinstance(target, (int, float)) and not isinstance(target, bool):
            return target
        active.add(value)
        try:
            if isinstance(target, dict) and (
                {"id", "name", "severity"} <= target.keys() or "incidents" in target
            ):
                return {key: deref_nuxt(data, item, budget, active, depth + 1)
                        for key, item in target.items()}
            if isinstance(target, list) and target and type(target[0]) is int:
                return [deref_nuxt(data, item, budget, active, depth + 1) for item in target]
        finally:
            active.remove(value)
        return target
    return value


def parse_checkly(body: str, row: CatalogEntry) -> CompanyResult:
    data = extract_nuxt_data(body)
    incidents: list[dict[str, str]] = []
    budget = [MAX_PARSE_NODES]
    if data:
        for value in data:
            if not isinstance(value, dict):
                continue
            for key, index in value.items():
                if not str(key).startswith("unresolved-incidents-"):
                    continue
                payload = deref_nuxt(data, index, budget)
                raw_incidents = []
                if isinstance(payload, dict):
                    raw_incidents = payload.get("incidents") or []
                elif isinstance(payload, list):
                    raw_incidents = payload
                for item in raw_incidents:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name") or "").strip()
                    state = str(
                        item.get("lastUpdateStatus") or item.get("status") or ""
                    ).strip().lower()
                    severity = str(item.get("severity") or "").strip().lower()
                    if name:
                        incidents.append(
                            {"name": name, "status": state, "severity": severity}
                        )
    if not incidents and re.search(r"all systems operational", body, re.I):
        return build_company_result(
            row,
            indicator="none",
            label="All systems operational",
            degraded=False,
        )
    if not incidents:
        raise ValueError("could not read Checkly status page")
    degraded = bool(incidents)
    indicator = "none"
    if degraded:
        indicator = "minor"
        for item in incidents:
            if item.get("severity") in {"major", "critical"}:
                indicator = "major"
                break
    return build_company_result(
        row,
        indicator=indicator,
        label=label_for(
            indicator,
            incidents[0]["name"] if incidents else "All systems operational",
            degraded,
        ),
        degraded=degraded,
        incidents=incidents,
    )


class _HeadingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._capture = False
        self.headings: list[str] = []
        self._buf: list[str] = []
        self._length = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"h1", "h2"} and len(self.headings) < MAX_STATUS_HEADINGS:
            self._capture = True
            self._buf = []
            self._length = 0

    def handle_endtag(self, tag: str) -> None:
        if tag in {"h1", "h2"} and self._capture:
            text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
            if text:
                self.headings.append(text)
            self._capture = False

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._length += len(data)
            if self._length > MAX_SOURCE_STRING:
                raise ValueError("Status heading exceeds string limit")
            self._buf.append(data)


def parse_deepseek(body: str, row: CatalogEntry) -> CompanyResult:
    checked_body(body)
    parser = _HeadingParser()
    parser.feed(body)
    heading = " ".join(parser.headings[:MAX_STATUS_HEADINGS])
    if heading and DEEPSEEK_BAD_RE.search(heading):
        return build_company_result(
            row,
            indicator="minor",
            label=heading,
            degraded=True,
        )
    if heading and DEEPSEEK_OK_RE.search(heading):
        return build_company_result(
            row,
            indicator="none",
            label="All systems operational",
            degraded=False,
        )
    if DEEPSEEK_OK_RE.search(body):
        return build_company_result(
            row,
            indicator="none",
            label="All systems operational",
            degraded=False,
        )
    if DEEPSEEK_BAD_RE.search(body):
        return build_company_result(
            row,
            indicator="minor",
            label="Degraded performance",
            degraded=True,
        )
    raise ValueError("could not read DeepSeek status heading")


def strip_midjourney_markup(text: str) -> str:
    return re.sub(r"\*\*", "", str(text or "")).strip()


def parse_midjourney(body: str, row: CatalogEntry) -> CompanyResult:
    data = parse_json(body)
    if not isinstance(data, dict):
        raise ValueError("Midjourney payload is not an object")
    overall = str(data.get("overall_status") or "").strip().lower()
    if overall not in {"success", "warning", "error"}:
        raise ValueError("Midjourney payload has an unknown overall status")
    if not isinstance(data.get("headlines"), list):
        raise ValueError("Midjourney payload has no headlines list")
    incidents = []
    headline_worst = "success"
    first_ok = ""
    for item in data.get("headlines") or []:
        if not isinstance(item, dict):
            continue
        state = str(item.get("status") or "").strip().lower()
        message = strip_midjourney_markup(item.get("message") or item.get("label") or "")
        if not message:
            continue
        if state in {"error", "warning"}:
            incidents.append({"name": message, "status": state})
            if state == "error":
                headline_worst = "error"
            elif headline_worst != "error":
                headline_worst = "warning"
        elif not first_ok:
            first_ok = message
    worst = "error" if overall == "error" or headline_worst == "error" else (
        "warning" if overall == "warning" or headline_worst == "warning" else "success"
    )
    degraded = worst in {"error", "warning"}
    if worst == "error":
        indicator = "major"
    elif worst == "warning":
        indicator = "minor"
    else:
        indicator = "none"
    return build_company_result(
        row,
        indicator=indicator,
        label=label_for(indicator, incidents[0]["name"] if incidents else first_ok, degraded),
        degraded=degraded,
        incidents=incidents,
    )


def parse_deepinfra(body: str, row: CatalogEntry) -> CompanyResult:
    data = parse_json(body)
    if not isinstance(data, dict):
        raise ValueError("DeepInfra payload is not an object")
    if not isinstance(data.get("overallStatus"), str):
        raise ValueError("DeepInfra payload has no overall status")
    if not isinstance(data.get("services"), list):
        raise ValueError("DeepInfra payload has no services list")
    overall = str(data["overallStatus"]).strip().upper()
    if not overall:
        raise ValueError("DeepInfra overall status is empty")
    components = []
    for item in data.get("services") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("displayName") or item.get("publicId") or "").strip()
        state = str(item.get("status") or "OPERATIONAL").strip().lower()
        if name:
            components.append({"name": name, "status": state})
    incidents = []
    for item in data.get("activeIncidents") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("title") or item.get("name") or "").strip()
        state = str(item.get("status") or "").strip().lower()
        if name:
            incidents.append({"name": name, "status": state})
    service_hit = any(
        str(item.get("status") or "").upper() not in DEEPINFRA_OK | {"UNDER_MAINTENANCE"}
        for item in (data.get("services") or [])
        if isinstance(item, dict)
    )
    degraded = overall not in DEEPINFRA_OK or service_hit or bool(incidents)
    if overall in {"MAJOR_OUTAGE", "DOWN"}:
        indicator = "critical"
    elif overall == "PARTIAL_OUTAGE":
        indicator = "major"
    elif degraded:
        indicator = "minor"
    else:
        indicator = "none"
    return build_company_result(
        row,
        indicator=indicator,
        label=label_for(
            indicator,
            incidents[0]["name"] if incidents else overall.replace("_", " ").title(),
            degraded,
        ),
        degraded=degraded,
        incidents=incidents,
        components=components,
    )


PARSERS = {
    "statuspage": parse_statuspage,
    "instatus": parse_instatus,
    "betterstack": parse_betterstack,
    "google-cloud": parse_google_cloud,
    "rss": parse_rss,
    "checkly": parse_checkly,
    "deepseek": parse_deepseek,
    "midjourney": parse_midjourney,
    "deepinfra": parse_deepinfra,
}
