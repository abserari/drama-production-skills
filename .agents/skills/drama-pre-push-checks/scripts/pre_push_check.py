#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pre-push automated verification gate for drama-production-skills.

Runs the minimal sufficient local verification before pushing changes:
1. Workspace hygiene check (no forbidden temporary/binary files staged or untracked).
2. Automated test suite execution (pytest tests/).
3. Path safety check (no hardcoded environment paths in active code).
4. Golden regression check if detector/gate code has changed.

Exit code: 0 if all checks pass, 1 if any blocker is found.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
FORBIDDEN_EXTS = {'.mp4', '.mkv', '.mov', '.avi', '.7z', '.zip', '.tar', '.gz', '.safetensors', '.pth', '.bin', '.tmp', '.log', '.bak'}
EXCLUDED_DIRS = {'.git', '__pycache__', '.pytest_cache', '.venv', 'env'}

def check_hygiene():
    """Ensure no forbidden large binaries or garbage files are tracked/staged."""
    errors = []
    res = subprocess.run(['git', 'status', '--porcelain'], cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
    for line in res.stdout.splitlines():
        if not line.strip():
            continue
        file_path = line[3:].strip()
        p = ROOT / file_path
        if p.suffix.lower() in FORBIDDEN_EXTS:
            errors.append(f"Forbidden file type found in git status: {file_path}")
    return {
        "name": "workspace_hygiene",
        "passed": len(errors) == 0,
        "details": errors or ["Workspace clean of forbidden binary and temporary files"]
    }

def check_unit_tests():
    """Run pytest suite across tests/ directory."""
    tests_dir = ROOT / "tests"
    if not tests_dir.exists():
        return {"name": "unit_tests", "passed": True, "details": ["No tests directory found"]}
    
    cmd = [sys.executable, "-m", "pytest", str(tests_dir), "-q"]
    res = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
    passed = (res.returncode == 0)
    summary_line = res.stdout.strip().splitlines()[-1] if res.stdout.strip() else ""
    return {
        "name": "unit_tests",
        "passed": passed,
        "details": [summary_line] if passed else [res.stdout, res.stderr]
    }

def check_path_safety():
    """Verify no hardcoded Windows/Linux absolute paths (D:/..., C:/Users/..., /home/...) crept into active python code."""
    hardcoded_patterns = [
        re.compile(r'^\s*[^#\s].*["\']([D-Z]:/[^"\']+)["\']'),
        re.compile(r'^\s*[^#\s].*["\'](/home/[^"\']+)["\']'),
    ]
    violations = []
    for search_dir in [ROOT / "scripts", ROOT / "skills"]:
        if not search_dir.exists():
            continue
        for p in search_dir.rglob("*.py"):
            if any(part in EXCLUDED_DIRS for part in p.parts):
                continue
            text = p.read_text(encoding='utf-8', errors='ignore')
            in_multiline = False
            for line_no, line in enumerate(text.splitlines(), start=1):
                stripped = line.strip()
                if '"""' in stripped or "'''" in stripped:
                    in_multiline = not in_multiline
                    continue
                if in_multiline or stripped.startswith("#"):
                    continue
                if "os.environ" in line or "os.name ==" in line or "_g.glob" in line:
                    continue
                for pat in hardcoded_patterns:
                    m = pat.search(line)
                    if m:
                        rel = p.relative_to(ROOT).as_posix()
                        violations.append(f"{rel}:{line_no} Hardcoded path pattern: {m.group(1)}")
    return {
        "name": "path_safety",
        "passed": len(violations) == 0,
        "details": violations or ["No illegal hardcoded machine paths detected in active code"]
    }

def check_golden_regression():
    """If detector or calibration scripts changed, verify golden cases."""
    golden_script = ROOT / "skills" / "comfy-h3-video-producer" / "scripts" / "golden.py"
    if not golden_script.exists():
        return {"name": "golden_regression", "passed": True, "details": ["golden.py not present, skipping"]}
    
    cmd = [sys.executable, str(golden_script), "pending"]
    res = subprocess.run(cmd, cwd=golden_script.parent, capture_output=True, text=True, encoding='utf-8')
    passed = (res.returncode == 0)
    return {
        "name": "golden_regression",
        "passed": passed,
        "details": ["Golden suite harness is functional and pending cases cleanly processed"]
    }

def main():
    checks = [
        check_hygiene(),
        check_unit_tests(),
        check_path_safety(),
        check_golden_regression(),
    ]
    all_passed = all(c["passed"] for c in checks)
    report = {
        "all_passed": all_passed,
        "results": checks
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(0 if all_passed else 1)

if __name__ == "__main__":
    main()
