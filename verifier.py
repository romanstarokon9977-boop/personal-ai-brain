"""
Verifier — модуль проверки качества сгенерированного кода.

Проверяет:
- синтаксис Python (ast.parse)
- возможность импорта (без выполнения __main__)
- базовые эвристики (дубли, размер)

Возвращает детальный отчёт об ошибках и предупреждениях.
"""

import ast
import re
import tempfile
import importlib.util
import sys
import os
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
    Пытается импортировать код как модуль, НЕ выполняя блок __main__.

    Это безопасная проверка: если в коде ошибки уровня импорта
    (например, NameError, ImportError) — они будут обнаружены.
    """
    # Убираем блок if __name__ == "__main__" для безопасного импорта
    safe_code = re.sub(
        r'if\s+__name__\s*==\s*["\']__main__["\']\s*:.*$',
        '# __main__ block removed for verification',
        code,
        flags=re.DOTALL | re.MULTILINE
    )

    try:
        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.py',
            delete=False,
            encoding='utf-8'
        ) as f:
            f.write(safe_code)
            temp_path = f.name

        spec = importlib.util.spec_from_file_location(
            "_verifier_temp",
            temp_path
        )
        module = importlib.util.module_from_spec(spec)

        # Не добавляем в sys.modules, чтобы не засорять
        spec.loader.exec_module(module)

        return {"ok": True, "errors": [], "module": module}

    except Exception as e:
        error_type = type(e).__name__
        return {
            "ok": False,
            "errors": [f"{error_type} при импорте: {str(e)}"],
            "line": getattr(e, 'lineno', None)
        }
    finally:
        try:
            if 'temp_path' in locals() and os.path.exists(temp_path):
                os.unlink(temp_path)
        except Exception:
            pass


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
            "import_ok": bool,    # импорт проходит
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
        "warnings": quality["warnings"],
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
