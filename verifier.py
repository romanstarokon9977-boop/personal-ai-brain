"""
Verifier — модуль проверки качества сгенерированного кода.

Проверяет:
- синтаксис Python (ast.parse)
- статическая проверка структуры import-операторов (без выполнения кода)
- базовые эвристики (дубли, размер)

Возвращает детальный отчёт об ошибках и предупреждениях.
"""

import ast
import difflib
import re
import os
import time as _time
from typing import Dict, List, Optional


# ============================================================
# ИЗВЛЕЧЕНИЕ КОДА ИЗ ОТВЕТА МОДЕЛИ
# ============================================================

def extract_python_blocks(text: str) -> List[str]:
    """
    Извлекает все блоки ```python ... ``` из текста.
    Если блоков нет — возвращает весь текст как один блок.
    """
    if not text:
        return []

    pattern = r"```python\s*(.*?)\s*```"
    matches = re.findall(pattern, text, re.DOTALL | re.IGNORECASE)

    if matches:
        return [m.strip() for m in matches if m.strip()]

    # Если нет markdown-блоков, пробуем найти любой блок кода
    pattern2 = r"```\s*(.*?)\s*```"
    matches2 = re.findall(pattern2, text, re.DOTALL)

    if matches2:
        return [m.strip() for m in matches2 if m.strip()]

    # Возвращаем весь текст как есть
    return [text.strip()] if text.strip() else []


# ============================================================
# ПРОВЕРКА СИНТАКСИСА
# ============================================================

def check_syntax(code: str) -> Dict:
    """
    Проверяет синтаксис Python-кода через ast.parse.

    Returns:
        {"ok": bool, "errors": [...], "line": int или None}
    """
    try:
        ast.parse(code)
        return {"ok": True, "errors": [], "line": None}
    except SyntaxError as e:
        return {
            "ok": False,
            "errors": [f"SyntaxError на строке {e.lineno}: {e.msg}"],
            "line": e.lineno
        }
    except Exception as e:
        return {
            "ok": False,
            "errors": [f"Ошибка разбора: {str(e)}"],
            "line": None
        }


# ============================================================
# СТАТИЧЕСКИЙ АНАЛИЗ: поиск неопределённых переменных
# ============================================================

def check_undefined_variables(code: str) -> Dict:
    """
    Статический анализ через AST для обнаружения использования
    неопределённых переменных (NameError).
    
    Это базовая проверка: находит обращения к именам, которые
    не определены в текущей области видимости.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return {"ok": True, "errors": []}  # синтаксис проверяется отдельно
    
    errors = []
    
    class NameChecker(ast.NodeVisitor):
        def __init__(self):
            self.defined_names = set()
            self.used_names = []
            
        def visit_FunctionDef(self, node):
            self.defined_names.add(node.name)
            for arg in node.args.args:
                self.defined_names.add(arg.arg)
            self.generic_visit(node)
            
        def visit_ClassDef(self, node):
            self.defined_names.add(node.name)
            self.generic_visit(node)
            
        def visit_Name(self, node):
            if isinstance(node.ctx, ast.Load):
                self.used_names.append((node.id, node.lineno))
            elif isinstance(node.ctx, ast.Store):
                self.defined_names.add(node.id)
            self.generic_visit(node)
            
        def visit_ExceptHandler(self, node):
            # except ValueError as ve: — переменная "ve" определяется здесь
            if node.name:
                self.defined_names.add(node.name)
            self.generic_visit(node)
            
        def visit_ExceptHandler(self, node):
            # except ValueError as ve: — переменная "ve" определяется здесь
            if node.name:
                self.defined_names.add(node.name)
            self.generic_visit(node)
            
        def visit_Import(self, node):
            for alias in node.names:
                name = alias.asname if alias.asname else alias.name.split('.')[0]
                self.defined_names.add(name)
            self.generic_visit(node)
            
        def visit_ImportFrom(self, node):
            for alias in node.names:
                name = alias.asname if alias.asname else alias.name
                self.defined_names.add(name)
            self.generic_visit(node)
    
    checker = NameChecker()
    checker.visit(tree)
    
    # Стандартные встроенные имена
    builtins = set([
        'print', 'len', 'range', 'int', 'float', 'str', 'list', 'dict',
        'set', 'tuple', 'bool', 'type', 'isinstance', 'issubclass',
        'abs', 'all', 'any', 'bin', 'chr', 'dir', 'divmod', 'enumerate',
        'filter', 'format', 'frozenset', 'getattr', 'globals', 'hasattr',
        'hash', 'help', 'hex', 'id', 'input', 'iter', 'map', 'max', 'min',
        'next', 'object', 'oct', 'open', 'ord', 'pow', 'property', 'repr',
        'reversed', 'round', 'setattr', 'slice', 'sorted', 'staticmethod',
        'sum', 'super', 'vars', 'zip', 'Exception', 'ValueError', 'TypeError',
        'KeyError', 'IndexError', 'AttributeError', 'ZeroDivisionError',
        'FileNotFoundError', 'RuntimeError', 'StopIteration', 'True', 'False',
        'None', 'NotImplemented', 'Ellipsis',
        '__name__', '__main__', '__file__', '__doc__', '__package__',
        '__spec__', '__loader__', '__builtins__'
    ])
    
    # Ищем неопределённые имена
    for name, lineno in checker.used_names:
        if name not in checker.defined_names and name not in builtins:
            # Пропускаем модульные атрибуты (например, math.sqrt)
            if '.' in name:
                continue
            errors.append(f"Возможно неопределённая переменная '{name}' на строке {lineno}")
    
    return {"ok": len(errors) == 0, "errors": errors[:5]}  # максимум 5 ошибок


# ============================================================
# ПРОВЕРКА ИМПОРТА (без выполнения __main__)
# ============================================================

def check_import(code: str) -> Dict:
    """
    Выполняет только статическую проверку импортов.

    Код модели не исполняется: проверка не подтверждает, что зависимости
    установлены или что модуль успешно импортируется во время выполнения.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return {
            "ok": False,
            "errors": [f"SyntaxError при статической проверке: {e.msg}"],
            "line": e.lineno,
            "module": None,
            "warnings": [],
        }
    except Exception as e:
        return {
            "ok": False,
            "errors": [f"{type(e).__name__} при статической проверке: {e}"],
            "line": getattr(e, "lineno", None),
            "module": None,
            "warnings": [],
        }

    import_count = sum(
        isinstance(node, (ast.Import, ast.ImportFrom))
        for node in ast.walk(tree)
    )
    return {
        "ok": True,
        "errors": [],
        "line": None,
        "module": None,
        "warnings": [
            "Runtime-импорт не выполнялся; наличие и совместимость зависимостей не подтверждены."
        ],
        "import_count": import_count,
    }

# ============================================================
# ЭВРИСТИКИ КАЧЕСТВА
# ============================================================

def check_quality(code: str) -> Dict:
    """
    Простые эвристики качества:
    - размер кода
    - наличие дублирующихся определений функций
    - наличие пустых блоков
    """
    warnings = []

    # Проверяем размер
    lines = code.split('\n')
    if len(lines) > 500:
        warnings.append(f"Код очень большой ({len(lines)} строк)")

    if len(lines) < 3:
        warnings.append("Код слишком короткий, возможно неполный")

    # Проверяем дубли определений функций
    func_pattern = r'def\s+(\w+)\s*\('
    func_names = re.findall(func_pattern, code)
    seen = set()
    duplicates = set()

    for name in func_names:
        if name in seen:
            duplicates.add(name)
        seen.add(name)

    errors = []

    if duplicates:
        errors.append(f"Дублирующиеся функции: {', '.join(sorted(duplicates))}")

    # Проверяем дубли классов
    class_pattern = r'class\s+(\w+)\s*[\(:]'
    class_names = re.findall(class_pattern, code)
    seen_classes = set()
    dup_classes = set()

    for name in class_names:
        if name in seen_classes:
            dup_classes.add(name)
        seen_classes.add(name)

    if dup_classes:
        warnings.append(f"Дублирующиеся классы: {', '.join(sorted(dup_classes))}")

    # Проверяем точки входа
    main_blocks = code.count('if __name__')
    if main_blocks > 1:
        warnings.append(f"Несколько блоков __main__ ({main_blocks})")

    return {
        "errors": errors,
        "warnings": warnings,
        "lines": len(lines),
        "functions": len(set(func_names)),
        "classes": len(set(class_names))
    }


# ============================================================
# ГЛАВНАЯ ФУНКЦИЯ ВЕРИФИКАЦИИ
# ============================================================

def verify_code(code: str, language: str = "python") -> Dict:
    """
    Полная проверка кода.

    Returns:
        {
            "ok": bool,           # код полностью валиден
            "syntax_ok": bool,    # синтаксис в порядке
            "import_ok": bool,    # статическая проверка import-операторов прошла
            "errors": [...],      # критические ошибки
            "warnings": [...],    # предупреждения
            "stats": {...}        # статистика
        }
    """
    if not code or not code.strip():
        return {
            "ok": False,
            "syntax_ok": False,
            "import_ok": False,
            "errors": ["Пустой код"],
            "warnings": [],
            "stats": {}
        }

    if language.lower() != "python":
        # Для других языков пока только базовая проверка
        return {
            "ok": True,
            "syntax_ok": True,
            "import_ok": True,
            "errors": [],
            "warnings": [f"Язык {language} пока не проверяется"],
            "stats": {"lines": len(code.split('\n'))}
        }

    # 1. Проверка синтаксиса
    syntax = check_syntax(code)

    if not syntax["ok"]:
        return {
            "ok": False,
            "syntax_ok": False,
            "import_ok": False,
            "errors": syntax["errors"],
            "warnings": [],
            "stats": {}
        }

    # 2. Проверка неопределённых переменных
    undefined_check = check_undefined_variables(code)
    
    # 3. Проверка импорта
    import_check = check_import(code)

    # 3. Проверка качества
    quality = check_quality(code)

    all_errors = []
    if not import_check["ok"]:
        all_errors.extend(import_check["errors"])
    
    all_errors.extend(quality.get("errors", []))
    all_errors.extend(undefined_check.get("errors", []))

    ok = syntax["ok"] and import_check["ok"] and len(all_errors) == 0

    return {
        "ok": ok,
        "syntax_ok": syntax["ok"],
        "import_ok": import_check["ok"],
        "errors": all_errors,
        "warnings": quality["warnings"] + import_check.get("warnings", []),
        "stats": {
            "lines": quality["lines"],
            "functions": quality["functions"],
            "classes": quality["classes"]
        }
    }


# ============================================================
# ФОРМАТИРОВАНИЕ ОТЧЁТА
# ============================================================

def format_report(report: Dict) -> str:
    """
    Форматирует отчёт для вывода пользователю.
    """
    lines = []

    if report["ok"]:
        lines.append("✅ Код прошёл проверку")
    else:
        lines.append("❌ Код содержит ошибки")

    if report.get("errors"):
        lines.append("\nОшибки:")
        for err in report["errors"]:
            lines.append(f"  • {err}")

    if report.get("warnings"):
        lines.append("\nПредупреждения:")
        for warn in report["warnings"]:
            lines.append(f"  ⚠ {warn}")

    stats = report.get("stats", {})
    if stats:
        lines.append(f"\nСтатистика: {stats.get('lines', 0)} строк, "
                     f"{stats.get('functions', 0)} функций, "
                     f"{stats.get('classes', 0)} классов")

    return "\n".join(lines)


# ============================================================
# VERIFIER v2 — ПРОВЕРКА ПОСЛЕ FILE_EDIT
# ============================================================

def verify_file_edit(real_path, old_content, new_content,
                     test_name=None, test_runner=None):
    """
    Проверка после file_edit.

    Порядок:
      1. diff (old_content vs new_content) → .backups/basename.diff_TIMESTAMP
      2. py_compile (если .py) — FAIL = rollback
      3. targeted test (если test_name и test_runner) — FAIL/ERROR = rollback

    Returns:
        {
            "ok": bool,
            "py_compile": "PASS" | "FAIL" | "SKIP",
            "diff_saved": str | None,
            "targeted_test": {name, status, result},
            "rollback": bool,
            "errors": [str],
        }
    """
    result = {
        "ok": True,
        "py_compile": "SKIP",
        "diff_saved": None,
        "targeted_test": {"name": test_name, "status": "SKIP", "result": None},
        "rollback": False,
        "errors": [],
    }

    # --- 1. DIFF ---
    try:
        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)
        diff_text = "".join(
            difflib.unified_diff(
                old_lines, new_lines,
                fromfile=real_path + " (before)",
                tofile=real_path + " (after)",
            )
        )

        backup_dir = os.path.join(
            os.path.dirname(os.path.realpath(__file__)),
            ".backups"
        )
        os.makedirs(backup_dir, exist_ok=True)
        base_name = os.path.basename(real_path)
        timestamp = _time.strftime("%Y%m%d_%H%M%S")
        diff_path = os.path.join(
            backup_dir,
            f"{base_name}.diff_{timestamp}"
        )
        with open(diff_path, "w", encoding="utf-8") as f:
            f.write(diff_text)

        result["diff_saved"] = diff_path
    except Exception as e:
        result["errors"].append(f"DIFF_SAVE_ERROR: {e}")
        result["ok"] = False
        try:
            with open(real_path, "w", encoding="utf-8") as f:
                f.write(old_content)
            result["rollback"] = True
        except Exception as rb_err:
            result["errors"].append(f"ROLLBACK_FAILED: {rb_err}")
        return result

    # --- 2. PY_COMPILE (только для .py) ---
    if real_path.endswith(".py"):
        try:
            import py_compile
            py_compile.compile(real_path, doraise=True)
            result["py_compile"] = "PASS"
        except py_compile.PyCompileError as e:
            result["py_compile"] = "FAIL"
            result["errors"].append(f"PY_COMPILE_FAILED: {e}")
            try:
                with open(real_path, "w", encoding="utf-8") as f:
                    f.write(old_content)
                result["rollback"] = True
            except Exception as rb_err:
                result["errors"].append(f"ROLLBACK_FAILED: {rb_err}")
            result["ok"] = False
            return result
        except Exception as e:
            result["py_compile"] = "FAIL"
            result["errors"].append(f"PY_COMPILE_EXCEPTION: {e}")
            try:
                with open(real_path, "w", encoding="utf-8") as f:
                    f.write(old_content)
                result["rollback"] = True
            except Exception as rb_err:
                result["errors"].append(f"ROLLBACK_FAILED: {rb_err}")
            result["ok"] = False
            return result

    # --- 3. TARGETED TEST ---
    if test_name and test_runner is not None:
        try:
            tr_result = test_runner({"scope": "targeted", "test": test_name})
            result["targeted_test"]["result"] = tr_result
            if tr_result.get("ok") is True:
                result["targeted_test"]["status"] = "PASS"
            else:
                result["targeted_test"]["status"] = "FAIL"
                result["errors"].append(f"TARGETED_TEST_FAILED: {test_name}")
                result["ok"] = False
        except Exception as e:
            result["targeted_test"]["status"] = "ERROR"
            result["errors"].append(f"TARGETED_TEST_EXCEPTION: {e}")
            result["ok"] = False

        # Неуспешный тест или исключение тестового раннера требуют отката.
        if result["targeted_test"]["status"] in ("FAIL", "ERROR"):
            try:
                with open(real_path, "w", encoding="utf-8") as f:
                    f.write(old_content)
                result["rollback"] = True
            except Exception as rb_err:
                result["errors"].append(f"ROLLBACK_FAILED: {rb_err}")
                result["rollback"] = False

    return result


# ============================================================
# VERIFIER v3 — ПРОВЕРКА ТЕКСТОВОГО ОТВЕТА МОДЕЛИ
# ============================================================

def verify_text_response(response, context=None) -> Dict:
    """
    Детерминированная проверка текстового ответа модели.

    НЕ оценивает смысловую правильность ответа.
    Проверяет только технические признаки:
      - empty       — пустой / whitespace
      - malformed   — ответ сам является технической ошибкой
      - incomplete  — явные признаки структурного/технического обрыва
      - suspicious  — пользовательский текст содержит внутренний debug-маркер
      - valid       — всё остальное

    Returns:
        {
            "ok": bool,          # True только для category == "valid"
            "category": str,     # valid | empty | malformed | incomplete | suspicious
            "errors": [str],     # критические причины
            "warnings": [str],   # некритические замечания
            "stats": {           # метрики текста
                "length": int,
                "lines": int,
                "words": int,
            },
            "reasons": [str],    # детальные причины решения
        }
    """
    result = {
        "ok": False,
        "category": "valid",
        "errors": [],
        "warnings": [],
        "stats": {"length": 0, "lines": 0, "words": 0},
        "reasons": [],
    }

    text = "" if response is None else str(response)
    stripped = text.strip()
    result["stats"]["length"] = len(text)
    result["stats"]["lines"] = len(text.splitlines()) if text else 0
    result["stats"]["words"] = len(stripped.split()) if stripped else 0

    # --- 1. EMPTY ---
    if not stripped:
        result["category"] = "empty"
        result["errors"].append("EMPTY_RESPONSE")
        result["reasons"].append("Ответ пустой или содержит только пробелы")
        return result

    # --- 2. MALFORMED: ответ САМ является технической ошибкой ---
    first_line = stripped.splitlines()[0] if stripped else ""
    is_short = len(stripped) <= 60

    # 2a. Traceback — только если ответ НАЧИНАЕТСЯ с него
    if first_line.startswith("Traceback (most recent call last)"):
        result["category"] = "malformed"
        result["errors"].append("MALFORMED_MARKER:Traceback")
        result["reasons"].append("Ответ начинается с Traceback (most recent call last)")
        return result

    # 2b. Одиночный технический код — весь ответ состоит из маркера.
    if is_short:
        # 2b-1. HTTP_4xx / HTTP_5xx — строго трёхзначный код
        if re.match(r'^HTTP_[45][0-9]{2}[.!]?$', stripped):
            code = stripped.rstrip(".!")
            result["category"] = "malformed"
            result["errors"].append(f"MALFORMED_MARKER:{code}")
            result["reasons"].append(f"Ответ состоит из HTTP-кода: {code!r}")
            return result

        # 2b-2. LOCAL_HTTP_NNN — строго трёхзначный код
        if re.match(r'^LOCAL_HTTP_[0-9]{3}[.!]?$', stripped):
            code = stripped.rstrip(".!")
            result["category"] = "malformed"
            result["errors"].append(f"MALFORMED_MARKER:{code}")
            result["reasons"].append(f"Ответ состоит из LOCAL HTTP-кода: {code!r}")
            return result

        # 2b-3. Именованные константы — точное совпадение
        single_code_markers = (
            "LOCAL_SERVICE_UNAVAILABLE",
            "LOCAL_TIMEOUT",
            "LOCAL_EMPTY_CHOICES",
            "LOCAL_EMPTY_RESPONSE",
            "TOOL_BRIDGE_EXCEPTION",
            "TOOL_BRIDGE_MAX_ITERATIONS_REACHED",
            "INVALID_TOOL_ARGUMENTS",
            "TOOL_CALL_MISSING_NAME",
            "PATH_NOT_ALLOWED",
            "COMMAND_NOT_ALLOWED",
            "ALL_MODELS_IN_COOLDOWN",
            "NO_MODEL_SELECTED",
            "INVALID_CONTROLLER_ROUTE",
            "GEMINI_API_KEY не установлен",
        )
        for marker in single_code_markers:
            if stripped == marker or stripped == marker + "." or stripped == marker + "!":
                result["category"] = "malformed"
                result["errors"].append(f"MALFORMED_MARKER:{marker}")
                result["reasons"].append(f"Ответ состоит из технического кода: {marker!r}")
                return result

    # 2c. <error>...</error> — только если ответ НАЧИНАЕТСЯ с <error>
    if first_line.startswith("<error>") or first_line.startswith("<ERROR>"):
        result["category"] = "malformed"
        result["errors"].append("MALFORMED_MARKER:error_tag")
        result["reasons"].append("Ответ начинается с тега <error>")
        return result

    # 2d. [Errno ...] — только если ответ НАЧИНАЕТСЯ с него
    if first_line.startswith("[Errno "):
        result["category"] = "malformed"
        result["errors"].append("MALFORMED_MARKER:errno")
        result["reasons"].append("Ответ начинается с [Errno ")
        return result

    # --- 3. INCOMPLETE: только явные детерминированные признаки ---
    fence_count = text.count("```")
    if fence_count % 2 == 1:
        result["category"] = "incomplete"
        result["errors"].append("UNCLOSED_CODE_FENCE")
        result["reasons"].append("Ответ содержит незакрытый блок ``` (нечётное число маркеров)")
        return result

    truncation_markers = (
        "<truncated>",
        "[truncated]",
        "<cut>",
        "[cut]",
        "…<end>",
    )
    for marker in truncation_markers:
        if marker in text:
            result["category"] = "incomplete"
            result["errors"].append(f"TRUNCATION_MARKER:{marker}")
            result["reasons"].append(f"Ответ содержит явный маркер обрыва: {marker!r}")
            return result

    # --- 4. SUSPICIOUS: только явные присвоения внутренних переменных ---
    suspicious_assignments = (
        "lock_type =", "lock_type=",
        "model_lock =", "model_lock=",
        "cooldown_until =", "cooldown_until=",
        "empty_streak =", "empty_streak=",
        "empty_cooldown_until =", "empty_cooldown_until=",
        "rate_429 =", "rate_429=",
    )
    for marker in suspicious_assignments:
        if marker in text:
            result["category"] = "suspicious"
            result["warnings"].append(f"SUSPICIOUS_MARKER:{marker}")
            result["reasons"].append(f"Ответ содержит внутреннее присвоение: {marker!r}")
            return result

    if "🔧 TOOL BRIDGE" in text and "итерация" in text:
        result["category"] = "suspicious"
        result["warnings"].append("SUSPICIOUS_MARKER:TOOL_BRIDGE")
        result["reasons"].append("Ответ содержит debug-блок TOOL BRIDGE")
        return result

    if "📐 Context Manager" in text:
        result["category"] = "suspicious"
        result["warnings"].append("SUSPICIOUS_MARKER:CONTEXT_MANAGER")
        result["reasons"].append("Ответ содержит debug-блок Context Manager")
        return result

    single_suspicious_codes = (
        "EMPTY_STREAK_COOLDOWN",
        "LOCAL_MODEL_IN_COOLDOWN",
        "RATE_LIMIT (429)",
    )
    if is_short:
        for marker in single_suspicious_codes:
            if stripped == marker or stripped == marker + ".":
                result["category"] = "suspicious"
                result["warnings"].append(f"SUSPICIOUS_MARKER:{marker}")
                result["reasons"].append(f"Ответ состоит из внутреннего кода: {marker!r}")
                return result

    # --- 5. VALID ---
    result["ok"] = True
    result["category"] = "valid"
    result["reasons"].append("Ответ прошёл детерминированные проверки")
    return result
