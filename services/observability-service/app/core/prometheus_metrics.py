"""Prometheus metrics registry and telemetry collectors for CodeBridge Platform."""

from __future__ import annotations

import time
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

# Shared isolated registry to prevent collisions with default root collectors
codebridge_metrics_registry = CollectorRegistry(auto_describe=True)

# 1. HTTP Request Metrics
HTTP_REQUESTS_TOTAL = Counter(
    "codebridge_http_requests_total",
    "Total count of HTTP requests processed across microservices",
    ["service", "method", "status_code"],
    registry=codebridge_metrics_registry,
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "codebridge_http_request_duration_seconds",
    "Histogram of HTTP request latency in seconds",
    ["service", "method", "endpoint"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=codebridge_metrics_registry,
)

# 2. Service Health & Uptime Status
SERVICE_HEALTH_STATUS = Gauge(
    "codebridge_service_health_status",
    "Current health status probe (1=HEALTHY/DEGRADED, 0=UNHEALTHY)",
    ["service"],
    registry=codebridge_metrics_registry,
)

SERVICE_HEALTHY_PERCENT = Gauge(
    "codebridge_services_healthy_percent",
    "Percentage of healthy core microservices in cluster",
    registry=codebridge_metrics_registry,
)

# 3. AI Code Context & LangSmith Performance Metrics
AI_AUDIT_REQUESTS_TOTAL = Counter(
    "codebridge_ai_audit_requests_total",
    "Total pull requests scanned by Gemini AI Forensic Auditor",
    ["status", "recommendation"],
    registry=codebridge_metrics_registry,
)

AI_AUDIT_SCORE = Histogram(
    "codebridge_ai_audit_score",
    "Distribution of AI Forensic Audit Scores (0-100)",
    buckets=(0, 25, 50, 70, 85, 90, 95, 100),
    registry=codebridge_metrics_registry,
)

AI_SECURITY_VULNERABILITIES_TOTAL = Counter(
    "codebridge_ai_security_vulnerabilities_total",
    "Total security vulnerabilities intercepted in freelancer code",
    registry=codebridge_metrics_registry,
)

AI_PROMPT_INJECTIONS_PREVENTED_TOTAL = Counter(
    "codebridge_ai_prompt_injections_prevented_total",
    "Total prompt injection vectors scrubbed by AST parser",
    registry=codebridge_metrics_registry,
)

LANGSMITH_TRACES_LOGGED_TOTAL = Counter(
    "codebridge_langsmith_traces_logged_total",
    "Total LLM execution traces tracked via LangSmith telemetry",
    ["project", "status"],
    registry=codebridge_metrics_registry,
)

# 4. Payment & Sovereign PayRail Financial Metrics
PAYMENT_ORDERS_TOTAL = Counter(
    "codebridge_payment_orders_total",
    "Total milestone escrow orders created",
    ["currency"],
    registry=codebridge_metrics_registry,
)

PAYMENT_ESCROW_VOLUME_PAISE = Counter(
    "codebridge_payment_escrow_volume_paise",
    "Total monetary volume held in RBI Nodal Escrow (in paise)",
    registry=codebridge_metrics_registry,
)

PAYMENT_SETTLEMENTS_TOTAL = Counter(
    "codebridge_payment_settlements_total",
    "Total milestone payouts released to developers",
    ["type"],  # 'instant', 'auto_released'
    registry=codebridge_metrics_registry,
)

PAYMENT_TDS_DEDUCTED_PAISE = Counter(
    "codebridge_payment_tds_deducted_paise",
    "Total Section 194-O TDS withheld for Indian tax compliance (in paise)",
    registry=codebridge_metrics_registry,
)


def export_prometheus_metrics() -> tuple[bytes, str]:
    """Serializes the CodeBridge Prometheus registry to standard text exposition format."""
    return generate_latest(codebridge_metrics_registry), CONTENT_TYPE_LATEST
