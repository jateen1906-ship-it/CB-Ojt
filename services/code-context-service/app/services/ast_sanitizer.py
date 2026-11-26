"""AST-based code comment sanitizer and anti-prompt-injection boundary."""

from __future__ import annotations

import ast
import io
import re
import tokenize
from typing import Any

from app.core.logging import get_logger

logger = get_logger("services.ast_sanitizer")


def sanitize_code_ast(source_code: str, filename: str = "code.py") -> tuple[str, list[str]]:
    """Sanitize source code by scrubbing all comments and docstrings via AST parsing.

    Returns:
        (sanitized_executable_code, list_of_extracted_isolated_comments)
    """
    extracted_comments: list[str] = []

    # If it is a Python file or generic Python diff, use tokenize + ast
    if filename.endswith(".py") or "def " in source_code or "import " in source_code:
        try:
            # 1. Tokenize to scrub single-line comments
            output_tokens = []
            readline = io.StringIO(source_code).readline
            tokens = tokenize.generate_tokens(readline)
            for tok in tokens:
                token_type = tok.type
                token_string = tok.string
                if token_type == tokenize.COMMENT:
                    cleaned_comment = token_string.lstrip("#").strip()
                    if cleaned_comment:
                        extracted_comments.append(cleaned_comment)
                else:
                    output_tokens.append(tok)

            untokenized = tokenize.untokenize(output_tokens)

            # 2. Parse AST to strip docstrings from Module, ClassDef, and FunctionDef
            tree = ast.parse(untokenized)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
                    if (
                        node.body
                        and isinstance(node.body[0], ast.Expr)
                        and isinstance(node.body[0].value, ast.Constant)
                        and isinstance(node.body[0].value.value, str)
                    ):
                        extracted_comments.append(node.body[0].value.value.strip())
                        node.body.pop(0)
                        if not node.body:
                            node.body.append(ast.Pass())

            clean_code = ast.unparse(tree)
            return clean_code, extracted_comments
        except Exception as exc:
            logger.debug("AST parsing fallback to regex for %s: %s", filename, exc)

    # Generic language regex scrubber (C, JS, TS, Go, Rust, Java, Python fallback)
    single_line_pattern = re.compile(r"(?://|#)\s*(.*)$", re.MULTILINE)
    multi_line_pattern = re.compile(r"/\*([\s\S]*?)\*/", re.MULTILINE)

    for match in single_line_pattern.finditer(source_code):
        text = match.group(1).strip()
        if text:
            extracted_comments.append(text)

    for match in multi_line_pattern.finditer(source_code):
        text = match.group(1).strip()
        if text:
            extracted_comments.append(text)

    # Strip comments from code
    no_multi = multi_line_pattern.sub("", source_code)
    clean_code = single_line_pattern.sub("", no_multi).strip()
    return clean_code, extracted_comments


def detect_hollow_mock_code(source_code: str) -> bool:
    """Detect hollow / mock code attacks where developer hardcodes trivial stubs."""
    try:
        tree = ast.parse(source_code)
        func_count = 0
        hollow_count = 0

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_count += 1
                # Check for empty or trivial single-statement body
                real_stmts = [stmt for stmt in node.body if not isinstance(stmt, ast.Pass)]
                if not real_stmts:
                    hollow_count += 1
                elif len(real_stmts) == 1 and isinstance(real_stmts[0], ast.Return):
                    ret_val = real_stmts[0].value
                    # e.g., return {"status": "ok"} or return True or return "ok"
                    if isinstance(ret_val, ast.Constant) and ret_val.value in {True, False, "ok", "success", ""}:
                        hollow_count += 1
                    elif isinstance(ret_val, ast.Dict) and len(ret_val.keys) <= 1:
                        hollow_count += 1

        if func_count > 0 and (hollow_count / func_count) >= 0.5:
            return True
    except Exception:
        pass

    # Regex heuristic fallback
    hollow_patterns = [
        re.compile(r"def\s+\w+\([^)]*\):\s*(?:pass|\.\.\.)", re.MULTILINE),
        re.compile(r"return\s*\{\s*[\"']status[\"']\s*:\s*[\"']ok[\"']\s*\}", re.IGNORECASE),
        re.compile(r"return\s*(?:True|['\"]success['\"])\s*(?:#.*)?$", re.MULTILINE),
    ]
    matches = sum(len(p.findall(source_code)) for p in hollow_patterns)
    return matches >= 2


def detect_security_vulnerabilities(source_code: str) -> list[str]:
    """Audit code for common critical security vulnerabilities."""
    findings: list[str] = []

    vuln_rules = [
        (re.compile(r"(?:eval|exec)\s*\("), "CWE-95: Use of dynamic code execution (eval/exec)"),
        (re.compile(r"subprocess\.(?:Popen|run|call)\s*\(.*shell\s*=\s*True", re.IGNORECASE), "CWE-78: Shell command injection risk with shell=True"),
        (re.compile(r"os\.system\s*\("), "CWE-78: Use of os.system() is vulnerable to command injection"),
        (re.compile(r"execute\s*\(\s*f[\"'].*\{"), "CWE-89: Potential SQL Injection via format string in execute()"),
        (re.compile(r"-----BEGIN (?:RSA )?PRIVATE KEY-----"), "CWE-798: Hardcoded cryptographic private key detected"),
        (re.compile(r"['\"](?:sk_live|ghp|xoxb)_[a-zA-Z0-9]{20,}['\"]"), "CWE-798: Hardcoded live API secret or token detected"),
        (re.compile(r"pickle\.loads?\s*\("), "CWE-502: Insecure deserialization with pickle"),
    ]

    for pattern, description in vuln_rules:
        if pattern.search(source_code):
            findings.append(description)

    return findings
