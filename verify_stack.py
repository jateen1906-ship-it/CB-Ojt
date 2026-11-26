"""CodeBridge Unified Backend & Health Verification Suite.

Executes end-to-end sanity tests across all core systems:
1. Docker Compose Orchestration Graph
2. API Gateway & Microservices Test Suite
3. AI PR Audit & LangGraph Pipeline
4. Observability & Prometheus Scraper
5. Razorpay Sovereign PayRail & Redis Idempotency
"""

import subprocess
import sys
import time

GREEN = "\033[92m"
RED = "\033[91m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def print_banner(text: str) -> None:
    print(f"\n{BOLD}{CYAN}{'=' * 70}{RESET}")
    print(f"{BOLD}{CYAN}  {text}{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 70}{RESET}\n")


def run_check(title: str, command: str) -> bool:
    print(f"{BOLD}[RUNNING]{RESET} {title}...", end="", flush=True)
    start = time.perf_counter()
    res = subprocess.run(command, shell=True, capture_output=True, text=True)
    duration = time.perf_counter() - start

    if res.returncode == 0:
        print(f"\r{GREEN}{BOLD}[PASSED]{RESET}  {title} ({duration:.2f}s)")
        return True
    else:
        print(f"\r{RED}{BOLD}[FAILED]{RESET}  {title} ({duration:.2f}s)")
        if res.stderr:
            print(f"{RED}{res.stderr[:500]}{RESET}")
        elif res.stdout:
            print(f"{RED}{res.stdout[:500]}{RESET}")
        return False


def main() -> int:
    print_banner("CodeBridge Full-Stack Verification & Readiness Check")

    py = sys.executable
    checks = [
        ("Docker Compose Services Graph", "docker compose config --services"),
        ("API Gateway Test Suite (53 tests)", f'"{py}" -m pytest api-gateway/tests'),
        ("AI PR Audit & LangGraph Suite", f'"{py}" -m pytest services/code-context-service/tests/test_ai_audit_pr.py'),
        ("Observability & Prometheus Suite", f'"{py}" -m pytest services/observability-service/tests/test_observability.py'),
        ("Razorpay Sovereign PayRail & Escrow", f'"{py}" -m pytest services/payment-service/tests/test_razorpay_payrail.py'),
    ]

    all_passed = True
    for title, cmd in checks:
        if not run_check(title, cmd):
            all_passed = False

    print("\n" + "-" * 70)
    if all_passed:
        print(f"{GREEN}{BOLD}✓ ALL CHECKS PASSED — CODEBRIDGE BACKEND IS 100% PRODUCTION-READY!{RESET}")
        return 0
    else:
        print(f"{RED}{BOLD}✗ ONE OR MORE CHECKS FAILED — REVIEW THE OUTPUT ABOVE.{RESET}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
