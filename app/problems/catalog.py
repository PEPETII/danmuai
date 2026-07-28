"""Stable problem catalog with i18n keys and default actions."""

from __future__ import annotations

from typing import Any

from app.problems.actions import parse_actions

PROBLEM_CATALOG: dict[str, dict[str, Any]] = {
    "CONFIG-001": {
        "severity": "warning",
        "category": "configuration",
        "title_key": "problem.config.title",
        "summary_key": "problem.config.summary",
        "cause_key": "problem.config.cause",
        "impact_key": "problem.config.impact",
        "suggestion_keys": (
            "problem.config.suggestion.checkProfile",
            "problem.config.suggestion.fillCredentials",
            "problem.config.suggestion.testConnection",
        ),
        "actions": (
            {
                "type": "navigate",
                "label_key": "problem.action.openModelSettings",
                "target": "settings/api",
            },
        ),
        "recoverable": True,
        "feedback_allowed": True,
    },
    "AI-AUTH-001": {
        "severity": "error",
        "category": "authentication",
        "title_key": "problem.aiAuth.title",
        "summary_key": "problem.aiAuth.summary",
        "cause_key": "problem.aiAuth.cause",
        "impact_key": "problem.aiAuth.impact",
        "suggestion_keys": (
            "problem.aiAuth.suggestion.checkKey",
            "problem.aiAuth.suggestion.checkEndpoint",
            "problem.aiAuth.suggestion.testConnection",
        ),
        "actions": (
            {
                "type": "navigate",
                "label_key": "problem.action.openModelSettings",
                "target": "settings/api",
            },
            {
                "type": "probe_connection",
                "label_key": "problem.action.retryConnection",
            },
        ),
        "recoverable": True,
        "feedback_allowed": True,
    },
    "AI-BALANCE-001": {
        "severity": "error",
        "category": "account",
        "title_key": "problem.aiBalance.title",
        "summary_key": "problem.aiBalance.summary",
        "cause_key": "problem.aiBalance.cause",
        "impact_key": "problem.aiBalance.impact",
        "suggestion_keys": (
            "problem.aiBalance.suggestion.checkBalance",
            "problem.aiBalance.suggestion.switchProvider",
        ),
        "actions": (),
        "recoverable": True,
        "feedback_allowed": True,
    },
    "AI-RATE-001": {
        "severity": "warning",
        "category": "rate_limit",
        "title_key": "problem.aiRate.title",
        "summary_key": "problem.aiRate.summary",
        "cause_key": "problem.aiRate.cause",
        "impact_key": "problem.aiRate.impact",
        "suggestion_keys": (
            "problem.aiRate.suggestion.wait",
            "problem.aiRate.suggestion.reduceFrequency",
        ),
        "actions": (),
        "recoverable": True,
        "feedback_allowed": True,
    },
    "AI-MODEL-001": {
        "severity": "error",
        "category": "model",
        "title_key": "problem.aiModel.title",
        "summary_key": "problem.aiModel.summary",
        "cause_key": "problem.aiModel.cause",
        "impact_key": "problem.aiModel.impact",
        "suggestion_keys": (
            "problem.aiModel.suggestion.checkModelId",
            "problem.aiModel.suggestion.selectValidModel",
        ),
        "actions": (
            {
                "type": "navigate",
                "label_key": "problem.action.openModelSettings",
                "target": "settings/api",
            },
        ),
        "recoverable": True,
        "feedback_allowed": True,
    },
    "AI-TIMEOUT-001": {
        "severity": "warning",
        "category": "timeout",
        "title_key": "problem.aiTimeout.title",
        "summary_key": "problem.aiTimeout.summary",
        "cause_key": "problem.aiTimeout.cause",
        "impact_key": "problem.aiTimeout.impact",
        "suggestion_keys": (
            "problem.aiTimeout.suggestion.retry",
            "problem.aiTimeout.suggestion.checkNetwork",
        ),
        "actions": (
            {
                "type": "probe_connection",
                "label_key": "problem.action.retryConnection",
            },
        ),
        "recoverable": True,
        "feedback_allowed": True,
    },
    "NETWORK-001": {
        "severity": "error",
        "category": "network",
        "title_key": "problem.network.title",
        "summary_key": "problem.network.summary",
        "cause_key": "problem.network.cause",
        "impact_key": "problem.network.impact",
        "suggestion_keys": (
            "problem.network.suggestion.checkConnection",
            "problem.network.suggestion.retryLater",
        ),
        "actions": (
            {
                "type": "probe_connection",
                "label_key": "problem.action.retryConnection",
            },
        ),
        "recoverable": True,
        "feedback_allowed": True,
    },
    "CAPTURE-001": {
        "severity": "error",
        "category": "capture",
        "title_key": "problem.capture.title",
        "summary_key": "problem.capture.summary",
        "cause_key": "problem.capture.cause",
        "impact_key": "problem.capture.impact",
        "suggestion_keys": (
            "problem.capture.suggestion.checkDisplay",
            "problem.capture.suggestion.checkRegion",
        ),
        "actions": (
            {
                "type": "navigate",
                "label_key": "problem.action.openCaptureSettings",
                "target": "settings/capture",
            },
        ),
        "recoverable": True,
        "feedback_allowed": True,
    },
    "DISPLAY-001": {
        "severity": "warning",
        "category": "display",
        "title_key": "problem.display.title",
        "summary_key": "problem.display.summary",
        "cause_key": "problem.display.cause",
        "impact_key": "problem.display.impact",
        "suggestion_keys": (
            "problem.display.suggestion.checkScreenIndex",
            "problem.display.suggestion.reconnectDisplay",
        ),
        "actions": (
            {
                "type": "navigate",
                "label_key": "problem.action.openCaptureSettings",
                "target": "settings/capture",
            },
        ),
        "recoverable": True,
        "feedback_allowed": True,
    },
    "WEBVIEW-001": {
        "severity": "fatal",
        "category": "runtime",
        "title_key": "problem.webview.title",
        "summary_key": "problem.webview.summary",
        "cause_key": "problem.webview.cause",
        "impact_key": "problem.webview.impact",
        "suggestion_keys": (
            "problem.webview.suggestion.installWebView2",
        ),
        "actions": (),
        "recoverable": False,
        "feedback_allowed": False,
    },
    "WEBVIEW-002": {
        "severity": "fatal",
        "category": "runtime",
        "title_key": "problem.webviewStartup.title",
        "summary_key": "problem.webviewStartup.summary",
        "cause_key": "problem.webviewStartup.cause",
        "impact_key": "problem.webviewStartup.impact",
        "suggestion_keys": (
            "problem.webviewStartup.suggestion.restart",
            "problem.webviewStartup.suggestion.checkLog",
        ),
        "actions": (),
        "recoverable": False,
        "feedback_allowed": False,
    },
    "STORAGE-001": {
        "severity": "error",
        "category": "storage",
        "title_key": "problem.storage.title",
        "summary_key": "problem.storage.summary",
        "cause_key": "problem.storage.cause",
        "impact_key": "problem.storage.impact",
        "suggestion_keys": (
            "problem.storage.suggestion.checkDisk",
            "problem.storage.suggestion.retrySave",
        ),
        "actions": (),
        "recoverable": True,
        "feedback_allowed": True,
    },
    "KNOWLEDGE-001": {
        "severity": "error",
        "category": "knowledge",
        "title_key": "problem.knowledge.title",
        "summary_key": "problem.knowledge.summary",
        "cause_key": "problem.knowledge.cause",
        "impact_key": "problem.knowledge.impact",
        "suggestion_keys": (
            "problem.knowledge.suggestion.checkSource",
            "problem.knowledge.suggestion.retryImport",
        ),
        "actions": (
            {
                "type": "navigate",
                "label_key": "problem.action.openKnowledge",
                "target": "content/knowledge",
            },
        ),
        "recoverable": True,
        "feedback_allowed": True,
    },
    "TTS-001": {
        "severity": "warning",
        "category": "tts",
        "title_key": "problem.tts.title",
        "summary_key": "problem.tts.summary",
        "cause_key": "problem.tts.cause",
        "impact_key": "problem.tts.impact",
        "suggestion_keys": (
            "problem.tts.suggestion.checkTtsSettings",
            "problem.tts.suggestion.retry",
        ),
        "actions": (
            {
                "type": "navigate",
                "label_key": "problem.action.openTtsSettings",
                "target": "settings/tts",
            },
        ),
        "recoverable": True,
        "feedback_allowed": True,
    },
    "INTERNAL-001": {
        "severity": "fatal",
        "category": "internal",
        "title_key": "problem.internal.title",
        "summary_key": "problem.internal.summary",
        "cause_key": "problem.internal.cause",
        "impact_key": "problem.internal.impact",
        "suggestion_keys": (
            "problem.internal.suggestion.restart",
            "problem.internal.suggestion.submitFeedback",
        ),
        "actions": (),
        "recoverable": False,
        "feedback_allowed": True,
    },
}


def catalog_entry(code: str) -> dict[str, Any]:
    entry = PROBLEM_CATALOG.get(code)
    if entry is None:
        return PROBLEM_CATALOG["INTERNAL-001"]
    return entry


def catalog_actions(code: str) -> tuple:
    return parse_actions(catalog_entry(code).get("actions"))
