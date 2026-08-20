from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_web(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def init_section(source: str) -> str:
    return source.split("async function init() {", 1)[1].split(
        "\ndocument.addEventListener(", 1
    )[0]


def test_core_interactions_bind_before_bootstrap_requests():
    source = read_web("web/static/app.js")
    binding = source.split("function bindCoreInteractions() {", 1)[1].split(
        "\n}\n\nasync function init()", 1
    )[0]
    init = init_section(source)

    assert "document.querySelectorAll('#nav [data-page]')" in binding
    assert "initTheme" not in binding
    for marker in ("initErrorReporting", "initProblemDialog", "configureStatus", "bindSettingsControls"):
        assert marker in binding
    assert init.index("bindCoreInteractions();") < init.index("await refreshSession();")


def test_bootstrap_failures_are_independent_and_visible():
    source = read_web("web/static/app.js")
    init = init_section(source)

    for marker in (
        "['announcements', loadAnnouncementsReadState]",
        "['model-catalog', loadModelCatalog]",
        "['providers', loadProviders]",
        "['config-defaults', loadConfigDefaults]",
        "runBootstrapTask('config', reloadConfigFromServer)",
        "runBootstrapTask('screens', loadScreens)",
        "runBootstrapTask('status'",
    ):
        assert marker in init
    assert "recordBootstrapFailure" in source
    assert "fetch(`${API.base}/api/status`)" not in init


def test_provider_bootstrap_reuses_api_fetch_and_validates_payloads():
    source = read_web("web/static/modules/settings-providers.js")

    assert "apiFetch" in source
    assert "new AbortController()" in source
    assert "fetchProviderBootstrap('/api/providers')" in source
    assert "fetchProviderBootstrap('/api/provider-rules')" in source
    assert "validateProvidersPayload" in source
    assert "validateProviderRulesPayload" in source
    assert "renderProviderEmptyFallback()" in source
    assert "throw error;" in source
    assert "fetch(" not in source


def test_settings_bootstrap_reuses_api_fetch_and_validates_payloads():
    source = read_web("web/static/modules/settings.js")

    assert "apiFetch" in source
    assert "new AbortController()" in source
    assert "validateConfigPayload" in source
    assert "validateConfigDefaultsPayload" in source
    assert "validateScreensPayload" in source
    assert "await fetchSettingsBootstrap('/api/config/defaults')" in source
    assert "awaitSettingsBootstrap(reloadConfigFromServerImpl(), '/api/config')" in source
    assert "await fetchSettingsBootstrap('/api/screens')" in source
    assert "setConfigDefaultsCache(defaults)" in source
    assert "fetch(" not in source


def test_transport_retains_http_and_json_error_boundary():
    source = read_web("web/static/modules/transport.js")

    assert "if (!res.ok)" in source
    assert "return res.json();" in source


def test_transport_clears_stale_session_on_refresh_failure():
    source = read_web("web/static/modules/transport.js")

    assert "export function clearSessionCredentials()" in source
    assert "reportAuthFailure(error, 'apiFetch')" in source
    assert ".catch((e) => reportAuthFailure(e, 'ws-status'))" in source
    assert ".catch((e) => reportAuthFailure(e, 'ws-logs'))" in source
    assert "onAuthFailure" in source


def test_visibility_resume_uses_single_flight_transport_entry():
    app_js = read_web("web/static/app.js")
    transport_js = read_web("web/static/modules/transport.js")

    visibility_block = app_js.split("document.addEventListener('visibilitychange'", 1)[1].split(
        "\n});", 1
    )[0]
    assert "resumeRealtimeTransport()" in visibility_block
    assert "startRealtimeTransport()" not in visibility_block
    assert "bootstrapLogsFromServer" not in visibility_block

    assert "export function resumeRealtimeTransport()" in transport_js
    assert "let resumeTransportPromise = null" in transport_js
    assert "function scheduleLogsBootstrap(" in transport_js
    assert "function isTransportHealthy()" in transport_js
    assert "handlers.bootstrapLogs(0)" not in transport_js
    assert "scheduleLogsBootstrap(REALTIME.lastLogsPollTs)" in transport_js
