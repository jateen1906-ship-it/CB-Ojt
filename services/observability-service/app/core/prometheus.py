"""Prometheus metrics registry and collectors for CodeBridge platform telemetry."""

from __future__ import annotations

import time
from typing import Any

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

# Dedicated Registry for CodeBridge Platform
REGISTRY = CollectorRegistry(auto_describe=True)

# 1. HTTP Traffic Metrics
HTTP_REQUESTS_TOTAL = Counter(
    "codebridge_http_requests_total",
    "Total HTTP requests received across CodeBridge services",
    ["service", "method", "endpoint", "status_code"],
    registry=REGISTRY,
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "codebridge_http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["service", "method", "endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=REGISTRY,
)

# 2. Service Health Gauges
SERVICE_HEALTH_STATUS = Gauge(
    "codebridge_service_health_status",
    "Health status of microservices (1 = HEALTHY/DEGRADED, 0 = UNHEALTHY/DOWN)",
    ["service", "endpoint"],
    registry=REGISTRY,
)

# 3. Escrow & PayRail Metrics
ESCROW_TRANSACTIONS_TOTAL = Counter(
    "codebridge_escrow_transactions_total",
    "Total PayRail escrow milestone transactions",
    ["status", "currency"],
    registry=REGISTRY,
)

ESCROW_VOLUME_PAISE_TOTAL = Counter(
    "codebridge_escrow_volume_paise_total",
    "Total monetary volume processed in paise",
    ["currency"],
    registry=REGISTRY,
)

# 4. AI Audit & LangSmith Telemetry Metrics
AI_AUDIT_REQUESTS_TOTAL = Counter(
    "codebridge_ai_audit_requests_total",
    "Total PR forensic audits processed by AI",
    ["recommendation", "status"],
    registry=REGISTRY,
)

AI_AUDIT_SCORE = Histogram(
    "codebridge_ai_audit_score",
    "Distribution of Gemini/AI PR requirement audit scores (0-100)",
    buckets=(10, 25, 50, 75, 85, 90, 95, 100),
    registry=REGISTRY,
)

AI_SECURITY_VULNERABILITIES_TOTAL = Counter(
    "codebridge_ai_security_vulnerabilities_total",
    "Total critical security vulnerabilities intercepted by AI forensic scanner",
    ["severity"],
    registry=REGISTRY,
)

AI_HOLLOW_MOCK_DETECTED_TOTAL = Counter(
    "codebridge_ai_hollow_mock_detected_total",
    "Total hollow/mock code attempts detected and rejected",
    registry=REGISTRY,
)

LANGGRAPH_WORKFLOW_RUNS_TOTAL = Counter(
    "codebridge_langgraph_workflow_runs_total",
    "Total multi-agent LangGraph audit state graph runs",
    ["status", "recommendation"],
    registry=REGISTRY,
)

LANGGRAPH_STEP_LATENCY_SECONDS = Histogram(
    "codebridge_langgraph_step_latency_seconds",
    "Latency of individual LangGraph state graph agent nodes",
    ["node"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    registry=REGISTRY,
)

# 5. System Active Users & Projects
ACTIVE_USERS_GAUGE = Gauge(
    "codebridge_active_users_total",
    "Total active registered users on CodeBridge",
    ["role"],
    registry=REGISTRY,
)

ACTIVE_PROJECTS_GAUGE = Gauge(
    "codebridge_active_projects_total",
    "Total projects categorized by lifecycle status",
    ["status"],
    registry=REGISTRY,
)


def export_prometheus_metrics() -> tuple[bytes, str]:
    """Generate latest Prometheus metrics formatted bytes and header."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
