"""
Read-only self-inspection module for Personal AI Brain.

Собирает диагностическую информацию о проекте:
- наличие и SHA-256 ключевых файлов;
- сравнение с Golden-эталонами;
- состояние Git (только чтение);
- предупреждения о неполноте диагностики.

Не изменяет состояние проекта. Не читает секреты.
Не импортирует другие модули проекта (brain.py и т.д.).
Не использует временные файлы в проекте.
"""

import os
import hashlib
import subprocess


SECRET_BASENAMES = {
    "config.py",
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
}

SECRET_SUFFIXES = (".pem", ".key", ".crt", ".p12", ".pfx")

SECRET_SUBSTRINGS = ("credential", "token", "secret", "password", "apikey")


INSPECTED_FILES = (
    "brain.py",
    "tool_registry.py",
    "verifier.py",
    "memory/memory_core.py",
    "memory/fact_extractor.py",
    "auto_poster.py",
    "cpa_brain_bridge.py",
    "mcp_bridge.py",
    "context_manager.py",
)


GOLDEN_REFERENCES = {
    "brain.py": {
        "reference_path": "backups_golden/brain_GOLDEN_20261008_132201_filesearch_fifo_fixed.py",
        "expected_sha256": "ac88b1787bd4ebafba23b67e4fbc58aa2f43ce30d3aa99f730c570a10febc5d8",
        "verified": True,
        "verified_by": "roman_confirmation",
    },
    "tool_registry.py": {
        "reference_path": "backups_golden/tool_registry_GOLDEN_20260913_052650.py",
        "expected_sha256": "cc58d7529775dfdfaae577a7c6c7da73b9263adc0b3bcca04d9b8c9040c29e86",
        "verified": False,
        "verified_by": None,
    },
    "context_manager.py": {
        "reference_path": "backups_golden/context_manager_GOLDEN_20260913_052650.py",
        "expected_sha256": "89e8e9b9392968becf2dd72306793ed80c97fd261cae26e92beb9bcadc71698c",
        "verified": False,
        "verified_by": None,
    },
    "verifier.py": {
        "reference_path": ".backups/verifier.py.GOLDEN_20260928_031258_p1_1_pass",
        "expected_sha256": "aea30a8bd7033e1df01fd821518296a6704e45ecc53b933cf31c5e1ffda3c87d",
        "verified": True,
        "verified_by": "p1_1_pass",
    },
}


def _is_secret_basename(name):
    """Проверяет basename (не подстроку) на секретность."""
    if not name:
        return False
    base = os.path.basename(name)
    if base in SECRET_BASENAMES:
        return True
    if base.startswith(".env"):
        return True
    low = base.lower()
    if low.endswith(SECRET_SUFFIXES):
        return True
    return any(s in low for s in SECRET_SUBSTRINGS)


def _resolve_inside(rel_path, project_root):
    """Возвращает (real, contained, error). Симлинки разрешаются."""
    try:
        real_root = os.path.realpath(project_root)
        if os.path.isabs(rel_path):
            candidate = rel_path
        else:
            candidate = os.path.join(project_root, rel_path)
        real = os.path.realpath(candidate)
        if real == real_root or real.startswith(real_root + os.sep):
            return real, True, None
        return real, False, "OUTSIDE_PROJECT_ROOT"
    except Exception:
        return None, False, "RESOLVE_ERROR"


def sha256_file(path):
    """SHA-256 файла. Возвращает hex-строку или None."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _file_info(rel_path, project_root):
    info = {
        "exists": False,
        "size": None,
        "sha256": None,
        "readable": False,
        "is_secret": _is_secret_basename(rel_path),
        "error": None,
    }

    if info["is_secret"]:
        info["error"] = "SECRET_SKIPPED"
        return info

    real, contained, err = _resolve_inside(rel_path, project_root)
    if err or real is None:
        info["error"] = err or "RESOLVE_ERROR"
        return info
    if not os.path.isfile(real):
        info["error"] = "NOT_FOUND"
        return info

    info["exists"] = True
    try:
        info["size"] = os.path.getsize(real)
    except Exception:
        info["size"] = None

    sha = sha256_file(real)
    if sha is None:
        info["error"] = "READ_ERROR"
    else:
        info["sha256"] = sha
        info["readable"] = True
    return info


def _golden_info(rel_path, current_sha, project_root):
    result = {
        "reference_path": None,
        "reference_exists": False,
        "reference_sha256": None,
        "expected_reference_sha256": None,
        "reference_verified": False,
        "reference_verified_by": None,
        "current_sha256": current_sha,
        "status": "NO_REFERENCE",
        "detail": None,
    }

    ref = GOLDEN_REFERENCES.get(rel_path)
    if ref is None:
        return result

    result["reference_path"] = ref.get("reference_path")
    result["expected_reference_sha256"] = ref.get("expected_sha256")
    result["reference_verified"] = bool(ref.get("verified"))
    result["reference_verified_by"] = ref.get("verified_by")

    ref_path = ref.get("reference_path")
    if not ref_path:
        result["status"] = "NO_REFERENCE"
        return result

    if _is_secret_basename(ref_path):
        result["status"] = "SECRET_SKIPPED"
        return result

    real, contained, err = _resolve_inside(ref_path, project_root)
    if err or real is None:
        result["status"] = "REFERENCE_MISSING"
        result["detail"] = err or "RESOLVE_ERROR"
        return result
    if not os.path.isfile(real):
        result["status"] = "REFERENCE_MISSING"
        return result

    result["reference_exists"] = True
    ref_sha = sha256_file(real)
    result["reference_sha256"] = ref_sha

    if ref_sha is None:
        result["status"] = "UNKNOWN"
        return result

    expected = ref.get("expected_sha256")
    if not expected:
        result["status"] = "UNKNOWN"
        result["detail"] = "EXPECTED_SHA_MISSING"
        return result
    if ref_sha != expected:
        result["status"] = "REFERENCE_CORRUPTED"
        return result

    if current_sha is None:
        result["status"] = "UNKNOWN"
        return result

    if current_sha == ref_sha:
        result["status"] = "MATCH"
    else:
        result["status"] = "DIFFERS"
    return result


def _mask_path(p):
    """Маскирует basename секретного файла, сохраняя структуру директорий."""
    base = os.path.basename(p)
    if _is_secret_basename(base):
        d = os.path.dirname(p)
        return (d + os.sep + "[REDACTED_SECRET]") if d else "[REDACTED_SECRET]"
    return p


def _git_state(project_root):
    state = {
        "available": False,
        "error": None,
        "branch": None,
        "head": None,
        "ahead_of_origin": None,
        "behind_origin": None,
        "staged": [],
        "unstaged": [],
        "untracked": [],
    }

    def _run(args):
        try:
            p = subprocess.run(
                args,
                cwd=project_root,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if p.returncode != 0:
                return None
            return p.stdout
        except Exception:
            return None

    out = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    if out is None:
        state["error"] = "GIT_NOT_AVAILABLE"
        return state
    state["available"] = True
    state["branch"] = out.strip()

    out = _run(["git", "rev-parse", "--short", "HEAD"])
    if out is not None:
        state["head"] = out.strip()

    out = _run(["git", "rev-list", "--count", "origin/main..HEAD"])
    if out is not None:
        try:
            state["ahead_of_origin"] = int(out.strip())
        except ValueError:
            pass

    out = _run(["git", "rev-list", "--count", "HEAD..origin/main"])
    if out is not None:
        try:
            state["behind_origin"] = int(out.strip())
        except ValueError:
            pass

    try:
        p = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if p.returncode == 0 and p.stdout:
            for entry in p.stdout.split("\0"):
                if not entry or len(entry) < 3:
                    continue
                code = entry[:2]
                path = _mask_path(entry[3:])
                if "?" in code:
                    state["untracked"].append(path)
                else:
                    if code[0] not in (" ", "?"):
                        state["staged"].append(path)
                    if code[1] not in (" ", "?"):
                        state["unstaged"].append(path)
    except Exception:
        pass

    return state


def collect(project_root=None):
    """Read-only сборка диагностического отчёта."""
    try:
        if project_root is None:
            project_root = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.realpath(project_root)

        result = {
            "project_root": project_root,
            "files": {},
            "golden": {},
            "git": {},
            "diagnostics": {
                "warnings": [],
                "inconclusive": [],
            },
        }

        for rel_path in INSPECTED_FILES:
            fi = _file_info(rel_path, project_root)
            result["files"][rel_path] = fi

            gi = _golden_info(rel_path, fi.get("sha256"), project_root)
            result["golden"][rel_path] = gi

            if not fi["exists"] and not fi["is_secret"]:
                result["diagnostics"]["warnings"].append(
                    "missing_file:" + rel_path
                )
            if gi["status"] in ("REFERENCE_MISSING", "REFERENCE_CORRUPTED", "UNKNOWN"):
                tag = gi["status"].lower()
                if gi.get("detail") == "EXPECTED_SHA_MISSING":
                    tag = "expected_sha_missing"
                result["diagnostics"]["inconclusive"].append(
                    "golden_" + tag + ":" + rel_path
                )

        result["git"] = _git_state(project_root)
        if not result["git"]["available"]:
            result["diagnostics"]["inconclusive"].append("git_not_available")

        return {"ok": True, "error": None, "result": result}
    except Exception:
        return {"ok": False, "error": "COLLECT_FAILED", "result": None}
