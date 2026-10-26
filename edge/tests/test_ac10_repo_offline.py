"""AC10 gap-fill: repo-level Doc06 Phase 1 / Phase 8 offline-demo rows.

These check committed artifacts (frontend styles, compose file), so CI —
which runs pytest but not docker — catches a broken offline demo profile.
See ``project-state/AC10_TEST_COVERAGE.md``.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FRONTEND = REPO / "frontend"
FONTS_CSS = FRONTEND / "src" / "styles" / "fonts.css"
COMPOSE = REPO / "docker-compose.yml"

_EXTERNAL_URL = re.compile(r"https?://", re.IGNORECASE)
_CSS_URL = re.compile(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)")


def _frontend_style_files() -> list[Path]:
    return [FRONTEND / "index.html", *sorted((FRONTEND / "src").rglob("*.css"))]


# ---- Phase 1 Happy / Phase 8 Happy: offline — no CDN at runtime


def test_frontend_html_and_css_reference_no_external_urls():
    offenders = []
    for path in _frontend_style_files():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _EXTERNAL_URL.search(line):
                offenders.append(f"{path.relative_to(REPO)}:{lineno}: {line.strip()}")
    assert offenders == []


# ---- Phase 1 Happy: "Fonts load offline — Geist renders with no network"


def test_every_font_face_url_resolves_to_a_vendored_file():
    urls = _CSS_URL.findall(FONTS_CSS.read_text(encoding="utf-8"))
    assert urls, "fonts.css declares no @font-face sources"
    missing = [u for u in urls if not (FONTS_CSS.parent / u).resolve().is_file()]
    assert missing == []


# ---- Phase 1 Sad: "Corrupt compose → fail fast in CI"
# ---- Phase 8 Edge: "Cold boot → services start in order (db→broker→backend→frontend)"


def _compose_services() -> dict[str, str]:
    """Top-level service name → its indented body, from a plain text scan.

    Deliberately YAML-library-free: PyYAML is not a project dependency, and
    CI runs pytest without docker, so this is the check that can run there.
    """
    text = COMPOSE.read_text(encoding="utf-8")
    block = re.search(r"^services:\n(.*?)(?=^\S)", text, re.MULTILINE | re.DOTALL)
    assert block, "docker-compose.yml has no top-level services: block"
    services: dict[str, str] = {}
    for match in re.finditer(r"^  ([a-z][\w-]*):\n((?:    .*\n|\s*\n)*)", block.group(1), re.M):
        services[match.group(1)] = match.group(2)
    return services


def test_compose_defines_the_four_demo_services():
    assert set(_compose_services()) == {"mosquitto", "db", "backend", "frontend"}


def test_compose_encodes_the_documented_startup_order():
    services = _compose_services()
    assert "healthcheck:" in services["db"]
    backend = services["backend"]
    assert re.search(r"db:\s*\n\s*condition:\s*service_healthy", backend)
    assert re.search(r"mosquitto:\s*\n\s*condition:\s*service_started", backend)
    assert re.search(r"depends_on:\s*\n\s*-\s*backend", services["frontend"])


def test_compose_refuses_to_start_the_db_without_a_password():
    assert "POSTGRES_PASSWORD:?" in _compose_services()["db"]
