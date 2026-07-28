"""Unified structured problem reporting for DanmuAI."""

from app.problems.catalog import PROBLEM_CATALOG
from app.problems.classifier import (
    ProblemClassification,
    classify_http_status_error,
    classify_network_error,
    problem_code_for_http_error,
    problem_code_from_error_message,
)
from app.problems.model import ProblemAction, ProblemDescriptor
from app.problems.serializer import serialize_problem_descriptor, serialize_problem_summary
from app.problems.service import PROBLEM_DEDUP_WINDOW_SEC, ProblemService

__all__ = [
    "PROBLEM_CATALOG",
    "PROBLEM_DEDUP_WINDOW_SEC",
    "ProblemAction",
    "ProblemClassification",
    "ProblemDescriptor",
    "ProblemService",
    "classify_http_status_error",
    "classify_network_error",
    "problem_code_for_http_error",
    "problem_code_from_error_message",
    "serialize_problem_descriptor",
    "serialize_problem_summary",
]
