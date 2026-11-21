#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Context Manager — управление бюджетом контекста перед отправкой модели.
Независимый модуль. Не импортирует brain.py.

Этап A: приоритеты, бюджет, безопасное сокращение, диагностика.
"""

import json
from dataclasses import dataclass, field
from typing import Optional


# ============================================================
# Профили бюджета
# ============================================================

@dataclass
class ContextProfile:
    layer: str
    budget_chars: int       # общий бюджет контекста (символы)
    reserve_pct: float      # % запаса безопасности
    tool_result_max: int    # макс. размер одного tool result
    max_history_msgs: int   # макс. количество non-system сообщений

PROFILES = {
    "API": ContextProfile(
        layer="API",
        budget_chars=24000,
        reserve_pct=0.15,
        tool_result_max=3000,
        max_history_msgs=30,
    ),
    "LOCAL": ContextProfile(
        layer="LOCAL",
        budget_chars=6000,
        reserve_pct=0.20,
        tool_result_max=1500,
        max_history_msgs=12,
    ),
}


# Ф2 (BUG#11/#43): при усечении memory-блока до Core+tail сохраняются
# последние MEMORY_FACTS_TAIL символов фактов (вместо полного среза).
MEMORY_FACTS_TAIL = 400

def private_context_allowed(layer: str) -> bool:
    """Private memory, chat recall and user-authored skills are local-only.

    Unknown, missing and external layers fail closed. This policy is applied
    before private context is loaded or appended to model messages.
    """
    return layer == "LOCAL"


# ============================================================
# Приоритеты сообщений
# ============================================================

def _classify_message(msg: dict, is_last_tool_pair: bool) -> int:
    """
    Возвращает приоритет сообщения (меньше = важнее).
    P0=0  system / rules
    P1=1  последний tool_call + result
    P2=2  memory / recent history (последние N)
    P3=3  old history
    P4=4  duplicates / noise
    """
    role = msg.get("role", "")
    content_str = msg.get("content", "") or ""

    # P2: память (не вытесняет P0 rules и P1 tool results)
    if role == "system" and (msg.get("name") == "memory" or "Контекст профиля и среды" in content_str):
        return 2

    # P0: system prompt
    if role == "system":
        return 0

    # P1: последний tool pair
    if is_last_tool_pair:
        return 1

    # P4: пустые или служебные
    content = msg.get("content", "")
    if not content and not msg.get("tool_calls"):
        return 4

    # P2/P3 определяется позицией (обрабатывается в prepare_context)
    return -1  # маркер «определить позже»


# ============================================================
# Утилиты размера
# ============================================================

def _msg_size(msg: dict) -> int:
    """Оценка размера сообщения в символах."""
    size = len(msg.get("content", "") or "")
    # tool_calls тоже занимают место
    tc = msg.get("tool_calls")
    if tc:
        size += len(json.dumps(tc, ensure_ascii=False))
    # role + overhead
    size += 50
    return size


def _total_size(messages: list[dict]) -> int:
    return sum(_msg_size(m) for m in messages)


def _find_last_tool_pair_indices(messages: list[dict]) -> set:
    """Находит индексы последнего tool_call + его result."""
    indices = set()
    last_tc_idx = None
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if msg.get("tool_calls"):
            last_tc_idx = i
            break
    if last_tc_idx is not None:
        indices.add(last_tc_idx)
        # Ищем соответствующие tool results после assistant
        for j in range(last_tc_idx + 1, len(messages)):
            if messages[j].get("role") == "tool":
                indices.add(j)
            elif messages[j].get("role") == "user" and "[РЕЗУЛЬТАТ ИНСТРУМЕНТА]" in (messages[j].get("content", "") or ""):
                indices.add(j)
            else:
                break
    return indices


# ============================================================
# Head+Tail сокращение
# ============================================================

def _code_structural_trim(text: str, max_chars: int) -> str:
    """
    Структурное сокращение кода: сохраняет каркас файла.
    - Начало файла (imports, docstrings, константы)
    - Сигнатуры class/def/async def с уровнем вложенности
    - if __name__ == "__main__" и подобные конструкции
    - Конец файла
    Тела крупных блоков заменяются маркером сокращения.
    """
    import re

    lines = text.split("\n")
    total_len = len(text)

    if total_len <= max_chars:
        return text

    # Определяем сколько строк оставить в начале и конце
    head_lines = max(10, max_chars // 100)   # ~1% бюджета на начало
    tail_lines = max(5, max_chars // 200)    # ~0.5% бюджета на конец

    # Собираем структурные элементы из середины
    structural_lines = []
    in_body = False
    body_start_indent = -1

    for i, line in enumerate(lines):
        if i < head_lines or i >= len(lines) - tail_lines:
            continue  # эти строки войдут в head/tail напрямую

        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        # Пропускаем пустые строки и комментарии в середине
        if not stripped or stripped.startswith("#"):
            continue

        # Обнаруживаем начало блока (class/def/async def/if __name__)
        is_signature = bool(re.match(
            r"^(class |def |async def |if __name__|@\w+)", stripped
        ))

        if is_signature:
            # Если были в теле предыдущего блока — закрываем его маркером
            if in_body:
                structural_lines.append(" " * body_start_indent + "    ... [тело сокращено]")
                in_body = False

            # Сохраняем сигнатуру целиком (может быть многострочной, но берём первую строку)
            structural_lines.append(line.rstrip())
            body_start_indent = indent
            in_body = True
        elif in_body and indent <= body_start_indent and stripped:
            # Вышли из тела блока (меньший или равный отступ + непустая строка)
            structural_lines.append(" " * body_start_indent + "    ... [тело сокращено]")
            in_body = False

            # Проверяем, не является ли эта строка новой сигнатурой
            if re.match(r"^(class |def |async def |if __name__|@\w+)", stripped):
                structural_lines.append(line.rstrip())
                body_start_indent = indent
                in_body = True

    # Закрываем последний открытый блок
    if in_body:
        structural_lines.append(" " * body_start_indent + "    ... [тело сокращено]")

    # Собираем результат: head + структура + tail
    head = "\n".join(lines[:head_lines])
    tail = "\n".join(lines[-tail_lines:])
    structure = "\n".join(structural_lines)

    marker = "\n... [КОД СОКРАЩЁН: показаны imports и сигнатуры, тела функций опущены] ...\n"

    result = head + marker + structure + marker + tail

    # Если результат всё ещё слишком большой — уменьшаем компоненты
    if len(result) > max_chars:
        # Пробуем уменьшить структуру (убираем часть сигнатур из середины)
        if len(structural_lines) > 4:
            keep = max(2, len(structural_lines) * max_chars // len(result))
            structural_lines = structural_lines[:keep//2] + ["    ... [сигнатуры сокращены]"] + structural_lines[-keep//2:]
            structure = "\n".join(structural_lines)
            result = head + marker + structure + marker + tail

    # Финальная доводка: если результат > max_chars, агрессивно сокращаем,
    # но сохраняем сигнатуры (в отличие от head+tail, который их теряет).
    if len(result) > max_chars:
        # 1. Сохраняем критический tail (__main__, main()), если он был в конце
        crit_tail_lines = [l for l in lines[-tail_lines:] if "__main__" in l or "main()" in l]
        min_tail = ("\n" + "\n".join(crit_tail_lines)) if crit_tail_lines else ""
        result_min_tail = head + marker + structure + marker + min_tail
        if len(result_min_tail) <= max_chars:
            return result_min_tail
        # 2. Сокращаем head до минимума
        min_head = "\n".join(lines[:5])
        result_min = min_head + marker + structure + marker + min_tail
        if len(result_min) <= max_chars:
            return result_min
        # 3. Прореживаем сигнатуры: оставляем только class/def верхнего уровня
        top_level = [s for s in structural_lines
                     if s and not s.startswith(" ") and not s.startswith("\t")]
        if top_level:
            structure_top = "\n".join(top_level)
            result_top = min_head + marker + structure_top + marker + min_tail
            if len(result_top) <= max_chars:
                return result_top
        # 4. Абсолютный fallback: head + первые N сигнатур + min_tail
        first_sigs = structural_lines[:10]
        result_abs = min_head + marker + "\n".join(first_sigs) + marker + min_tail
        if len(result_abs) > max_chars:
            result_abs = result_abs[:max_chars]
        return result_abs

    return result


def _tree_structural_trim(text: str, max_chars: int) -> str:
    """
    Структурное сокращение дерева файлов.
    Поддерживает JSON-дерево (MCP directory_tree) и текстовое дерево (box-drawing).
    Сохраняет верхние уровни структуры, опускает глубокие подкаталоги и шум (.pyc, __pycache__).
    """
    import json
    import re

    stripped = text.strip()

    # --- Попытка парсинга как JSON-дерева ---
    if stripped.startswith("[") and '"name"' in text[:500]:
        try:
            tree_data = json.loads(stripped)
            if isinstance(tree_data, list):
                # Быстрая проверка: если маленький и без шума — возвращаем оригинал
                NOISE_MARKERS = ("__pycache__", ".pyc", ".pyo", "node_modules")
                has_noise = any(m in text for m in NOISE_MARKERS)
                if len(text) <= max_chars and not has_noise:
                    return text
                # Фильтрация шума ВСЕГДА применяется к JSON-деревьям
                result = _trim_json_tree(tree_data, max_chars)
                if len(result) <= max_chars:
                    return result
                return result
        except (json.JSONDecodeError, ValueError):
            pass

    # --- Текстовое дерево (box-drawing или ls-подобный вывод) ---
    NOISE_TEXT = ("__pycache__", ".pyc", ".pyo", "node_modules")
    has_noise_text = any(m in text for m in NOISE_TEXT)
    if len(text) <= max_chars and not has_noise_text:
        return text
    result = _trim_text_tree(text, max_chars)
    if len(result) <= max_chars:
        return result
    return result


def _trim_json_tree(nodes: list, max_chars: int) -> str:
    """Сокращает JSON-дерево: сохраняет структуру верхних уровней."""
    import json

    NOISE_DIRS = {"__pycache__", ".git", "node_modules", ".mypy_cache", ".pytest_cache"}
    NOISE_EXTS = {".pyc", ".pyo", ".class", ".o", ".so"}

    def prune(node, depth=0, max_depth=3):
        name = node.get("name", "")
        ntype = node.get("type", "")

        # Фильтруем шум
        if name in NOISE_DIRS:
            return {"name": name, "type": ntype, "_pruned": True}
        if any(name.endswith(ext) for ext in NOISE_EXTS):
            return None  # полностью убираем .pyc и т.д.

        result = {"name": name, "type": ntype}

        children = node.get("children", [])
        if children and depth < max_depth:
            pruned_children = []
            hidden_count = 0
            for child in children:
                pc = prune(child, depth + 1, max_depth)
                if pc is not None:
                    pruned_children.append(pc)
                else:
                    hidden_count += 1
            if pruned_children:
                result["children"] = pruned_children
            if hidden_count > 0:
                result["_hidden_files"] = hidden_count
        elif children and depth >= max_depth:
            result["_truncated"] = len(children)

        return result

    pruned = [prune(n) for n in nodes if n is not None]
    pruned = [p for p in pruned if p is not None]

    result = json.dumps(pruned, ensure_ascii=False, indent=2)

    # Если всё ещё слишком большой — уменьшаем max_depth
    if len(result) > max_chars:
        pruned_shallow = [prune(n, max_depth=2) for n in nodes if n is not None]
        pruned_shallow = [p for p in pruned_shallow if p is not None]
        result = json.dumps(pruned_shallow, ensure_ascii=False, indent=2)

    # Финальная гарантия размера
    if len(result) > max_chars:
        marker = "\n... [ДЕРЕВО СОКРАЩЕНО: показаны верхние уровни] ...\n"
        head_size = max_chars * 2 // 3
        tail_size = max_chars - head_size - len(marker)
        if tail_size > 0:
            result = result[:head_size] + marker + result[-tail_size:]
        else:
            result = result[:max_chars]

    return result


def _trim_text_tree(text: str, max_chars: int) -> str:
    """Сокращает текстовое дерево: сохраняет верхние уровни, фильтрует шум."""
    lines = text.split("\n")
    NOISE_PATTERNS = ["__pycache__", ".pyc", ".pyo", "node_modules", ".git/"]

    filtered = []
    for line in lines:
        # Пропускаем шумные строки
        if any(p in line for p in NOISE_PATTERNS):
            continue
        filtered.append(line)

    result = "\n".join(filtered)

    # После фильтрации шума результат может стать маленьким — это ОК
    if len(result) <= max_chars:
        return result

    # Head + tail с маркером
    marker = "\n... [ДЕРЕВО СОКРАЩЕНО: шумные файлы удалены, глубокие уровни опущены] ...\n"
    head_size = max_chars * 2 // 3
    tail_size = max_chars - head_size - len(marker)
    if tail_size > 0:
        return result[:head_size] + marker + result[-tail_size:]
    return result[:max_chars]


def _json_structural_trim(text: str, max_chars: int) -> str:
    """
    Структурное сокращение JSON с гарантией валидности результата.
    - Object: сохраняет ключи, сокращает значения рекурсивно
    - Array: сохраняет первые N элементов + _truncated count
    - Результат ВСЕГДА валидный JSON (проверяется через json.loads)
    - Fallback на head+tail только если структурное сокращение невозможно
    """
    import json

    stripped = text.strip()

    # Ранний выход
    if len(stripped) <= max_chars:
        return text

    # Парсим JSON
    try:
        data = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        # Не валидный JSON — fallback на head+tail
        return _head_tail_trim(text, max_chars)

    # Рекурсивное структурное сокращение
    pruned = _prune_json(data, max_chars)

    # Сериализуем компактно (без indent для экономии места)
    result = json.dumps(pruned, ensure_ascii=False, separators=(",", ":"))

    # Проверяем размер
    if len(result) <= max_chars:
        # Финальная проверка валидности
        try:
            json.loads(result)
            return result
        except Exception:
            pass

    # Если compact всё ещё большой — пробуем с минимальным форматированием
    # Убираем _truncated метаданные если они есть и уменьшаем массивы ещё сильнее
    pruned_aggressive = _prune_json(data, max_chars // 2)
    result = json.dumps(pruned_aggressive, ensure_ascii=False, separators=(",", ":"))

    if len(result) <= max_chars:
        try:
            json.loads(result)
            return result
        except Exception:
            pass

    # Крайний fallback: head+tail (результат может быть невалидным JSON)
    fallback = _head_tail_trim(text, max_chars)
    return fallback


def _prune_json(data, budget: int, depth: int = 0) -> object:
    """Рекурсивно сокращает JSON-структуру, сохраняя форму."""
    import json

    MAX_DEPTH = 5
    MAX_ARRAY_ITEMS = 10
    MAX_STRING_LEN = 200

    if depth > MAX_DEPTH:
        return "...[max depth]"

    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            pruned_val = _prune_json(value, budget, depth + 1)
            result[key] = pruned_val

        # Проверяем размер результата
        serialized = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        if len(serialized) > budget and len(result) > 2:
            # Убираем наименее важные ключи (последние)
            keys = list(result.keys())
            keep = max(2, len(keys) * budget // len(serialized))
            kept_keys = keys[:keep]
            removed = len(keys) - keep
            result = {k: result[k] for k in kept_keys}
            if removed > 0:
                result["_keys_removed"] = removed

        return result

    elif isinstance(data, list):
        if not data:
            return []

        original_len = len(data)

        # Сокращаем количество элементов
        keep_count = min(MAX_ARRAY_ITEMS, max(1, original_len * budget // max(len(json.dumps(data, ensure_ascii=False, separators=(",", ":"))), 1)))
        kept = [_prune_json(item, budget // max(keep_count, 1), depth + 1) for item in data[:keep_count]]

        if original_len > keep_count:
            kept.append({"_truncated": original_len - keep_count})

        return kept

    elif isinstance(data, str):
        if len(data) > MAX_STRING_LEN:
            return data[:MAX_STRING_LEN] + "...[truncated]"
        return data

    else:
        # int, float, bool, None — возвращаем как есть
        return data


def _search_structural_trim(text: str, max_chars: int, max_results: int = 8) -> str:
    """
    Структурное сокращение результатов поиска.
    Сохраняет первые N совпадений + метаданные об общем количестве.
    Поддерживает форматы: "path:line:content" и многострочные блоки.
    """
    import re

    if len(text) <= max_chars:
        return text

    lines = text.split("\n")
    
    # Парсим результаты поиска (формат path:line:content или блоки)
    results = []
    current_block = []
    
    for line in lines:
        # Проверяем формат path:line:content
        match = re.match(r"^([\w./\\-]+):(\d+):(.*)$", line)
        if match:
            if current_block:
                results.append("\n".join(current_block))
                current_block = []
            results.append(line)
        elif line.strip() and not line.startswith((" ", "\t")):
            # Новая запись без стандартного формата
            if current_block:
                results.append("\n".join(current_block))
                current_block = []
            current_block = [line]
        else:
            current_block.append(line)
    
    if current_block:
        results.append("\n".join(current_block))
    
    total_matches = len(results)
    
    if total_matches <= max_results:
        # Мало результатов — просто обрезаем каждый по длине
        trimmed_lines = []
        chars_used = 0
        marker = "\n... [РЕЗУЛЬТАТЫ ПОИСКА СОКРАЩЕНЫ] ...\n"
        reserve = len(marker) + 50
        
        for r in results:
            if chars_used + len(r) > max_chars - reserve:
                # Обрезаем этот результат
                remaining = max_chars - reserve - chars_used
                if remaining > 50:
                    trimmed_lines.append(r[:remaining] + "...")
                break
            trimmed_lines.append(r)
            chars_used += len(r) + 1
        
        return "\n".join(trimmed_lines) + marker
    
    # Много результатов — берём первые N + метаданные
    kept = results[:max_results]
    hidden = total_matches - max_results
    
    header = f"[Показано {max_results} из {total_matches} совпадений]\n"
    marker = f"\n... [ещё {hidden} совпадений скрыто для экономии контекста] ..."
    
    result_lines = [header]
    chars_used = len(header)
    reserve = len(marker) + 50
    
    for r in kept:
        line_with_newline = r + "\n"
        if chars_used + len(line_with_newline) > max_chars - reserve:
            # Обрезаем последний результат
            remaining = max_chars - reserve - chars_used
            if remaining > 50:
                result_lines.append(r[:remaining] + "...")
            break
        result_lines.append(r)
        chars_used += len(line_with_newline)
    
    result_lines.append(marker)
    result = "\n".join(result_lines)
    
    # Финальная гарантия размера
    if len(result) > max_chars:
        return _head_tail_trim(text, max_chars)
    
    return result


def _classify_result(content: str, tool_name: str = "") -> str:
    """
    Классифицирует тип содержимого tool result.
    Возвращает: "error" | "json" | "tree" | "code" | "search" | "text"
    Быстрая проверка по первым ~500 символам + эвристики.
    """
    if not content:
        return "text"

    head = content[:500]
    name_lower = tool_name.lower()

    # ERROR: явные маркеры ошибок
    if head.startswith(("ERROR:", "EXCEPTION:", "Traceback")) or \
       "PATH_OUTSIDE_ALLOWED_DIR" in head or \
       "PATH_NOT_ALLOWED" in head:
        return "error"

    # TREE: по имени инструмента или структуре
    if name_lower in ("directory_tree", "list_directory_with_sizes"):
        return "tree"
    # Текстовое дерево с box-drawing символами
    if "├──" in head or "└──" in head or "│" in head:
        return "tree"
    # JSON-дерево: массив объектов с name+type
    stripped = content.strip()
    if stripped.startswith("[") and '"name"' in head and '"type"' in head:
        return "tree"

    # JSON: начинается с { или [ и заканчивается соответствующей скобкой
    if stripped.startswith(("{", "[")):
        # Проверяем структурные признаки без парсинга обрезанного фрагмента
        if (stripped.startswith("{") and stripped.rstrip().endswith("}")) or \
           (stripped.startswith("[") and stripped.rstrip().endswith("]")):
            return "json"
        # Для очень больших JSON конец может быть обрезан — проверяем по началу
        # Наличие ключей или элементов массива в первых 500 символах
        if stripped.startswith("{") and '":"' in head:
            return "json"
        if stripped.startswith("[") and ("{" in head or '"' in head):
            return "json"

    # CODE: признаки исходного кода
    code_markers = ["def ", "class ", "import ", "from ", "function ",
                    "const ", "let ", "var ", "public ", "private "]
    code_count = sum(1 for m in code_markers if m in head)
    if code_count >= 2:
        return "code"
    # Одиночный маркер + структурные признаки
    if code_count >= 1 and ("\n    " in head or "\n\t" in head or "{" in head):
        return "code"
    # Расширенное окно для read_file: файлы с длинными заголовками/комментариями
    if name_lower == "read_file" and len(content) > 500:
        extended_head = content[:2000]
        ext_count = sum(1 for m in code_markers if m in extended_head)
        if ext_count >= 2:
            return "code"
        if ext_count >= 1 and ("\n    " in extended_head or "\n\t" in extended_head or "{" in extended_head):
            return "code"

    # SEARCH: результаты поиска с путями/номерами строк
    if name_lower in ("file_search", "search_files"):
        return "search"
    # Множественные совпадения формата "path:line:"
    import re
    if len(re.findall(r"[\w./]+:\d+:", head)) >= 2:
        return "search"

    return "text"


def _head_tail_trim(text: str, max_chars: int) -> str:
    """
    Сокращает текст: начало + конец вместо тупого среза.
    Этап B улучшит это до структурированного сокращения.
    """
    if len(text) <= max_chars:
        return text
    head_size = max_chars * 2 // 3
    tail_size = max_chars - head_size - 30  # 30 для маркера
    return (
        text[:head_size]
        + "\n... [СОКРАЩЕНО Context Manager] ...\n"
        + text[-tail_size:]
    )


# ============================================================
# Основной вход
# ============================================================

def _trim_memory_to_core(content: str) -> str:
    """Ф2 (BUG#11/#43): Core Rules + хвост свежих фактов при дефиците бюджета.
    Полный срез фактов заменён на Core + последние MEMORY_FACTS_TAIL символов
    фактов (рез по границе строки): самые свежие факты — в конце — выживают."""
    marker = "\nДополнительные релевантные факты:"
    if marker not in content:
        return content
    notice = "\n[... более старые факты опущены CM ...]"
    idx = content.index(marker)
    core_part = content[:idx].rstrip()
    facts_part = content[idx:]
    if len(facts_part) <= MEMORY_FACTS_TAIL + len(marker) + len(notice):
        return content
    tail = facts_part[-MEMORY_FACTS_TAIL:]
    nl = tail.find("\n")
    if nl != -1:
        tail = tail[nl + 1:]
    else:
        tail = tail.lstrip("\n")
    if not tail.strip():
        return core_part + marker + notice
    return core_part + marker + notice + "\n" + tail.rstrip()


def prepare_context(
    messages: list[dict],
    layer: str = "API",
    budget_chars: int = 0,
) -> tuple[list[dict], dict]:
    """
    Подготавливает messages для отправки модели.

    Args:
        messages: working_messages из run_with_tools / controller_execute
        layer: "API" или "LOCAL"
        budget_chars: переопределение бюджета (0 = авто по профилю)

    Returns:
        (prepared_messages, diagnostics)
    """
    profile = PROFILES.get(layer, PROFILES["API"])
    effective_budget = budget_chars if budget_chars > 0 else profile.budget_chars
    safe_budget = int(effective_budget * (1.0 - profile.reserve_pct))

    input_size = _total_size(messages)
    details = []

    # --- Шаг 1: Классификация и защита P0/P1 ---
    last_tool_indices = _find_last_tool_pair_indices(messages)

    # Разделяем system (P0) и остальные
    system_msgs = [m for m in messages if m.get("role") == "system"]
    non_system = []
    for i, m in enumerate(messages):
        if m.get("role") != "system":
            non_system.append((i, m))  # сохраняем оригинальный индекс

    # --- Шаг 2: Если уже в бюджете — возвращаем как есть ---
    if input_size <= safe_budget:
        diag = {
            "layer": layer,
            "input_size": input_size,
            "output_size": input_size,
            "budget": effective_budget,
            "safe_budget": safe_budget,
            "used_pct": round(input_size / effective_budget * 100, 1),
            "trimmed": False,
            "messages_in": len(messages),
            "messages_out": len(messages),
            "details": ["within budget, no trimming needed"],
        }
        return list(messages), diag

    details.append(f"over budget: {input_size} > {safe_budget}")

    # --- Шаг 3: Сокращение tool results (head+tail) ---
    # Head+tail применяется ко ВСЕМ длинным результатам, включая P1.
    # Защита P1 = не удалять сообщение целиком, а не "не сокращать содержимое".
    trimmed_messages = []
    for i, m in enumerate(messages):
        content = m.get("content", "") or ""
        role = m.get("role", "")
        is_tool_result = (
            role == "tool"
            or (role == "user" and "[РЕЗУЛЬТАТ ИНСТРУМЕНТА]" in content)
        )

        if is_tool_result and len(content) > profile.tool_result_max:
            # Определяем тип результата для выбора стратегии сокращения
            # Находим имя инструмента из предыдущего assistant сообщения
            _tool_name = ""
            if i > 0:
                prev = messages[i - 1] if i <= len(messages) else {}
                tc = prev.get("tool_calls", [])
                if tc:
                    try:
                        import json as _json
                        args = _json.loads(tc[0].get("function", {}).get("arguments", "{}"))
                        _tool_name = tc[0].get("function", {}).get("name", "")
                    except Exception:
                        pass
            result_type = _classify_result(content, _tool_name)
            if result_type == "code":
                new_content = _code_structural_trim(content, profile.tool_result_max)
            elif result_type == "tree":
                new_content = _tree_structural_trim(content, profile.tool_result_max)
            elif result_type == "json":
                new_content = _json_structural_trim(content, profile.tool_result_max)
            elif result_type == "search":
                new_content = _search_structural_trim(content, profile.tool_result_max)
            else:
                new_content = _head_tail_trim(content, profile.tool_result_max)
            saved = len(content) - len(new_content)
            details.append(f"tool result trimmed at idx {i}: -{saved} chars (head+tail)")
            new_msg = dict(m)
            new_msg["content"] = new_content
            trimmed_messages.append(new_msg)
        else:
            trimmed_messages.append(dict(m))

    current_size = _total_size(trimmed_messages)
    if current_size <= safe_budget:
        diag = {
            "layer": layer,
            "input_size": input_size,
            "output_size": current_size,
            "budget": effective_budget,
            "safe_budget": safe_budget,
            "used_pct": round(current_size / effective_budget * 100, 1),
            "trimmed": True,
            "messages_in": len(messages),
            "messages_out": len(trimmed_messages),
            "details": details,
        }
        return trimmed_messages, diag

    # --- Шаг 4: Удаление старой истории (P3) с конца ---
    # Сохраняем system + последние сообщения + последний tool pair
    sys_count = len(system_msgs)
    ns_msgs = [(i, m) for i, m in enumerate(trimmed_messages) if m.get("role") != "system"]

    # Определяем сколько recent сохранить (P2)
    recent_count = min(profile.max_history_msgs // 2, len(ns_msgs))
    recent_indices = {idx for idx, _ in ns_msgs[-recent_count:]}

    # Удаляем P3 (old history) с начала non-system, защищая last_tool_pair
    to_remove = set()
    for orig_idx, m in ns_msgs:
        if orig_idx in last_tool_indices:
            continue
        if orig_idx in recent_indices:
            continue
        # Это P3 — кандидат на удаление
        to_remove.add(orig_idx)

    result_msgs = [m for i, m in enumerate(trimmed_messages) if i not in to_remove]
    current_size = _total_size(result_msgs)
    if to_remove:
        details.append(f"removed {len(to_remove)} old history messages (P3)")

    # Мягкое сокращение памяти (P2) до Core Rules при дефиците бюджета
    if current_size > safe_budget:
        for idx_m, m in enumerate(result_msgs):
            c_str = m.get("content", "") or ""
            if m.get("role") == "system" and (m.get("name") == "memory" or "Контекст профиля и среды" in c_str):
                orig_c_len = len(c_str)
                core_only = _trim_memory_to_core(c_str)
                if len(core_only) < orig_c_len:
                    new_m = dict(m)
                    new_m["content"] = core_only
                    result_msgs[idx_m] = new_m
                    details.append(f"trimmed memory to Core+tail ({orig_c_len} -> {len(core_only)} chars)")
        current_size = _total_size(result_msgs)

    if current_size <= safe_budget:
        diag = {
            "layer": layer,
            "input_size": input_size,
            "output_size": current_size,
            "budget": effective_budget,
            "safe_budget": safe_budget,
            "used_pct": round(current_size / effective_budget * 100, 1),
            "trimmed": True,
            "messages_in": len(messages),
            "messages_out": len(result_msgs),
            "details": details,
        }
        return result_msgs, diag

    # --- Шаг 5: Принудительный trim последних tool results (кроме самого последнего) ---
    # Защищаем только САМЫЙ последний tool pair
    final_msgs = []
    last_tool_set = _find_last_tool_pair_indices(result_msgs)
    for i, m in enumerate(result_msgs):
        content = m.get("content", "") or ""
        if content and len(content) > profile.tool_result_max and i not in last_tool_set:
            # Не ломаем JSON повторным head+tail — сохраняем как есть
            stripped_c = content.strip()
            if stripped_c.startswith(("{", "[")):
                try:
                    import json as _j
                    _j.loads(stripped_c)
                    # Валидный JSON — не трогаем даже если длинный
                    final_msgs.append(m)
                    continue
                except Exception:
                    pass  # Невалидный JSON — применяем head+tail
            new_content = _head_tail_trim(content, profile.tool_result_max)
            new_msg = dict(m)
            new_msg["content"] = new_content
            final_msgs.append(new_msg)
            details.append(f"force-trimmed tool result at idx {i}")
        else:
            final_msgs.append(m)

    current_size = _total_size(final_msgs)
    details.append(f"final size: {current_size}, budget: {safe_budget}")

    diag = {
        "layer": layer,
        "input_size": input_size,
        "output_size": current_size,
        "budget": effective_budget,
        "safe_budget": safe_budget,
        "used_pct": round(current_size / effective_budget * 100, 1),
        "trimmed": True,
        "messages_in": len(messages),
        "messages_out": len(final_msgs),
        "details": details,
    }
    return final_msgs, diag


# ============================================================
# Тестовый блок
# ============================================================

if __name__ == "__main__":
    print("=" * 64)
    print("     CONTEXT MANAGER — ISOLATED TEST SUITE")
    print("=" * 64)

    passed = 0
    failed = 0

    def check(label: str, condition: bool, detail: str = ""):
        global passed, failed
        status = "✅" if condition else "❌"
        if condition:
            passed += 1
        else:
            failed += 1
        msg = f"  {status} {label}"
        if detail:
            msg += f" — {detail}"
        print(msg)

    # --- Test 1: Within budget — no trimming ---
    print("\n[1] Within Budget")
    msgs = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi!"},
    ]
    out, diag = prepare_context(msgs, "API")
    check("No trimming when within budget", not diag["trimmed"])
    check("Output == input count", len(out) == len(msgs))
    check("Used pct reasonable", diag["used_pct"] < 10)

    # --- Test 2: System messages always preserved ---
    print("\n[2] P0 Protection")
    big_history = [{"role": "user", "content": "x" * 500} for _ in range(100)]
    msgs = [
        {"role": "system", "content": "CRITICAL SYSTEM PROMPT"},
    ] + big_history
    out, diag = prepare_context(msgs, "LOCAL")
    has_system = any(m.get("role") == "system" and "CRITICAL" in m.get("content", "") for m in out)
    check("System message preserved", has_system)
    check("Output fits safe budget", diag["output_size"] <= diag["safe_budget"])

    # --- Test 3: Last tool pair protected ---
    print("\n[3] P1 Protection (Last Tool Pair)")
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "old" * 1000},
        {"role": "assistant", "content": "old answer" * 500},
        {"role": "user", "content": "query"},
        {"role": "assistant", "content": "calling tool", "tool_calls": [
            {"id": "call_1", "function": {"name": "read_file", "arguments": '{"path":"brain.py"}'}}
        ]},
        {"role": "tool", "tool_call_id": "call_1", "content": "IMPORTANT TOOL RESULT " * 200},
    ]
    out, diag = prepare_context(msgs, "API")
    has_tool_result = any("IMPORTANT TOOL RESULT" in (m.get("content", "") or "") for m in out)
    has_tool_call = any(m.get("tool_calls") for m in out)
    check("Last tool_call preserved", has_tool_call)
    check("Last tool result preserved", has_tool_result)

    # --- Test 4: Head+Tail trimming ---
    print("\n[4] Head+Tail Trimming")
    long_content = "A" * 2000 + "B" * 2000 + "C" * 2000
    # Добавляем историю чтобы превысить safe_budget API (20400)
    padding = [{"role": "user", "content": "pad_" + str(i) * 200} for i in range(80)]
    msgs = [
        {"role": "system", "content": "sys"},
    ] + padding + [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "a", "tool_calls": [
            {"id": "c1", "function": {"name": "read_file", "arguments": "{}"}}
        ]},
        {"role": "tool", "tool_call_id": "c1", "content": long_content},
    ]
    out, diag = prepare_context(msgs, "API")
    tool_msg = [m for m in out if m.get("role") == "tool"][0]
    tc = tool_msg.get("content", "")
    check("Head+Tail marker present", "СОКРАЩЕНО" in tc)
    check("Start preserved", tc.startswith("A"))
    check("End preserved", tc.rstrip().endswith("C"))
    check("Trimmed size <= max", len(tc) <= 3000 + 100)  # +100 tolerance

    # --- Test 5: LOCAL profile stricter ---
    print("\n[5] Profile Differences")
    msgs_medium = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "a", "tool_calls": [
            {"id": "c1", "function": {"name": "x", "arguments": "{}"}}
        ]},
        {"role": "tool", "tool_call_id": "c1", "content": "X" * 2500},
    ]
    out_api, diag_api = prepare_context(msgs_medium, "API")
    out_local, diag_local = prepare_context(msgs_medium, "LOCAL")
    check("LOCAL trims more aggressively",
          diag_local["output_size"] <= diag_api["output_size"])

    # --- Test 6: Old history removed before recent ---
    print("\n[6] History Priority (P3 before P2)")
    msgs = [
        {"role": "system", "content": "sys"},
    ]
    for i in range(50):
        msgs.append({"role": "user", "content": f"old_{i}"})
        msgs.append({"role": "assistant", "content": f"ans_{i}"})
    msgs.append({"role": "user", "content": "CURRENT QUERY"})

    out, diag = prepare_context(msgs, "LOCAL")
    has_current = any("CURRENT QUERY" in (m.get("content", "") or "") for m in out)
    check("Current query preserved", has_current)
    check("Old history trimmed", diag["messages_out"] < diag["messages_in"])
    check("Output within safe budget", diag["output_size"] <= diag["safe_budget"])

    # --- Test 7: Diagnostics completeness ---
    print("\n[7] Diagnostics")
    out, diag = prepare_context(msgs, "API")
    required_keys = {"layer", "input_size", "output_size", "budget",
                     "safe_budget", "used_pct", "trimmed",
                     "messages_in", "messages_out", "details"}
    missing = required_keys - set(diag.keys())
    check("All diagnostic keys present", len(missing) == 0,
          f"missing={missing}" if missing else "")
    check("used_pct is numeric", isinstance(diag["used_pct"], (int, float)))
    check("details is list", isinstance(diag["details"], list))

    # --- Test 8: Empty messages ---
    print("\n[8] Edge Cases")
    out, diag = prepare_context([], "API")
    check("Empty input → empty output", len(out) == 0)
    check("Empty input not trimmed", not diag["trimmed"])

    # --- Test 9: Only system ---
    out, diag = prepare_context([{"role": "system", "content": "only sys"}], "LOCAL")
    check("Only system preserved", len(out) == 1)

    # --- Test 10: Custom budget override ---
    print("\n[9] Custom Budget Override")
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "X" * 1000},
    ]
    out, diag = prepare_context(msgs, "API", budget_chars=500)
    check("Custom budget applied", diag["budget"] == 500)
    check("Safe budget = 85% of custom", diag["safe_budget"] == 425)

    # --- Test B1: Classification ---
    print("\n[B1] Result Classification")

    check("Error: ERROR: prefix",
          _classify_result("ERROR: file not found") == "error")
    check("Error: EXCEPTION: prefix",
          _classify_result("EXCEPTION: timeout") == "error")
    check("Error: PATH_OUTSIDE_ALLOWED_DIR",
          _classify_result("PATH_OUTSIDE_ALLOWED_DIR: path=/etc/passwd") == "error")
    check("Error: Traceback",
          _classify_result("Traceback (most recent call last):\n  File ...") == "error")

    check("Tree: directory_tree tool name",
          _classify_result('[{"name":"x"}]', "directory_tree") == "tree")
    check("Tree: box-drawing chars",
          _classify_result("project/\n├── src/\n│   └── main.py\n└── README.md") == "tree")
    check("Tree: JSON array with name+type",
          _classify_result('[{"name":"brain.py","type":"file"},{"name":"src","type":"directory"}]') == "tree")

    check("JSON: valid object",
          _classify_result('{"key": "value", "count": 42}') == "json")
    check("JSON: valid array",
          _classify_result('[1, 2, 3, "test"]') == "json")
    check("JSON: invalid falls through",
          _classify_result('{not valid json at all') != "json")

    check("Code: Python function",
          _classify_result("import os\n\ndef read_file(path):\n    with open(path) as f:\n        return f.read()") == "code")
    check("Code: class definition",
          _classify_result("class ToolRegistry:\n    def __init__(self):\n        self._tools = {}") == "code")

    check("Search: file_search tool name",
          _classify_result("brain.py:42:def main():", "file_search") == "search")
    check("Search: multiple path:line: matches",
          _classify_result("src/a.py:10:foo\nsrc/b.py:20:bar\nsrc/c.py:30:baz") == "search")

    check("Text: plain text fallback",
          _classify_result("Just some regular text without special markers.") == "text")
    check("Text: empty content",
          _classify_result("") == "text")
    check("Text: markdown-ish",
          _classify_result("# Heading\nSome paragraph text here.") == "text")

    # --- Test B2.1: Code Structural Trim ---
    print("\n[B2.1] Code Structural Trim")

    # Генерируем большой Python-файл
    code_lines = ["import os", "import sys", "from pathlib import Path", ""]
    code_lines.append("CONSTANT = 42")
    code_lines.append("")
    for i in range(30):
        code_lines.append(f"def function_{i}(arg1, arg2=None):")
        code_lines.append(f'    """Docstring for function {i}."""')
        for j in range(20):
            code_lines.append(f"    x_{j} = arg1 + {j}")
        code_lines.append(f"    return x_0")
        code_lines.append("")
    code_lines.append('if __name__ == "__main__":')
    code_lines.append("    main()")
    big_code = "\n".join(code_lines)

    trimmed_code = _code_structural_trim(big_code, 1500)
    check("Code trim: smaller than max", len(trimmed_code) <= 1500,
          f"len={len(trimmed_code)}")
    check("Code trim: has trim marker",
          "КОД СОКРАЩЁН" in trimmed_code or "СОКРАЩЕНО" in trimmed_code)
    check("Code trim: preserves imports", "import os" in trimmed_code)
    check("Code trim: preserves signatures or head",
          "def function_" in trimmed_code or "import" in trimmed_code)
    check("Code trim: preserves __main__ or tail",
          '__name__ == "__main__"' in trimmed_code or "main()" in trimmed_code)
    check("Code trim: body reduced (no deep internals)",
          "x_15 = arg1" not in trimmed_code or "тело сокращено" in trimmed_code or "СОКРАЩЕНО" in trimmed_code)

    # Маленький код не должен тримиться
    small_code = "def hello():\n    return 'hi'"
    check("Code trim: small code unchanged",
          _code_structural_trim(small_code, 1500) == small_code)

    # Проверка что classify→code→structural trim работает через prepare_context
    padding_b2 = [{"role": "user", "content": "pad_" + str(i) * 200} for i in range(80)]
    msgs_b2 = [
        {"role": "system", "content": "sys"},
    ] + padding_b2 + [
        {"role": "user", "content": "read brain.py"},
        {"role": "assistant", "content": "calling read_file", "tool_calls": [
            {"id": "c1", "function": {"name": "read_file", "arguments": '{"path":"brain.py"}'}}
        ]},
        {"role": "tool", "tool_call_id": "c1", "content": big_code},
    ]
    out_b2, diag_b2 = prepare_context(msgs_b2, "API")
    tool_out = [m for m in out_b2 if m.get("role") == "tool"]
    if tool_out:
        tc = tool_out[0].get("content", "")
        check("Integration: code result uses structural trim",
              "КОД СОКРАЩЁН" in tc or "тело сокращено" in tc,
              f"len={len(tc)}")
    else:
        check("Integration: tool message present", False, "NO TOOL MSG")

    # --- Test B2.2: Tree Structural Trim ---
    print("\n[B2.2] Tree Structural Trim")

    # JSON-дерево (как от MCP directory_tree)
    json_tree = json.dumps([
        {"name": "src", "type": "directory", "children": [
            {"name": "main.py", "type": "file"},
            {"name": "utils.py", "type": "file"},
            {"name": "__pycache__", "type": "directory", "children": [
                {"name": "main.cpython-311.pyc", "type": "file"},
                {"name": "utils.cpython-311.pyc", "type": "file"},
            ]},
        ]},
        {"name": "tests", "type": "directory", "children": [
            {"name": "test_main.py", "type": "file"},
        ]},
        {"name": "README.md", "type": "file"},
        {"name": "brain.cpython-311.pyc", "type": "file"},
    ], ensure_ascii=False)

    trimmed_tree = _tree_structural_trim(json_tree, 500)
    check("Tree JSON: smaller than max", len(trimmed_tree) <= 500,
          f"len={len(trimmed_tree)}")
    check("Tree JSON: preserves top-level names",
          "src" in trimmed_tree and "README.md" in trimmed_tree)
    check("Tree JSON: filters __pycache__",
          "__pycache__" not in trimmed_tree or "_pruned" in trimmed_tree)
    check("Tree JSON: filters .pyc files",
          ".pyc" not in trimmed_tree)

    # Текстовое дерево (box-drawing)
    text_tree = """project/
├── src/
│   ├── main.py
│   ├── utils.py
│   └── __pycache__/
│       ├── main.cpython-311.pyc
│       └── utils.cpython-311.pyc
├── tests/
│   └── test_main.py
└── README.md"""

    trimmed_text_tree = _tree_structural_trim(text_tree, 300)
    check("Tree text: smaller than max", len(trimmed_text_tree) <= 300,
          f"len={len(trimmed_text_tree)}")
    check("Tree text: preserves structure",
          "src/" in trimmed_text_tree and "README.md" in trimmed_text_tree)
    check("Tree text: filters __pycache__",
          "__pycache__" not in trimmed_text_tree)
    check("Tree text: filters .pyc",
          ".pyc" not in trimmed_text_tree)

    # Маленькое дерево не тримится
    small_tree = json.dumps([{"name": "a.py", "type": "file"}])
    check("Tree: small unchanged",
          _tree_structural_trim(small_tree, 500) == small_tree)

    # Интеграция через prepare_context
    padding_tree = [{"role": "user", "content": "pad_" + str(i) * 200} for i in range(80)]
    big_json_tree = json.dumps([
        {"name": f"dir_{i}", "type": "directory", "children": [
            {"name": f"file_{j}.py", "type": "file"} for j in range(20)
        ]} for i in range(30)
    ])
    msgs_tree = [
        {"role": "system", "content": "sys"},
    ] + padding_tree + [
        {"role": "user", "content": "show tree"},
        {"role": "assistant", "content": "calling directory_tree", "tool_calls": [
            {"id": "t1", "function": {"name": "directory_tree", "arguments": '{"path":"."}'}}
        ]},
        {"role": "tool", "tool_call_id": "t1", "content": big_json_tree},
    ]
    out_tree, diag_tree = prepare_context(msgs_tree, "API")
    tool_tree = [m for m in out_tree if m.get("role") == "tool"]
    if tool_tree:
        tc = tool_tree[0].get("content", "")
        check("Integration: tree result trimmed",
              len(tc) <= 3000 + 100, f"len={len(tc)}")
    else:
        check("Integration: tree tool msg present", False, "NO TOOL MSG")

    # --- Test B2.3: JSON Structural Trim ---
    print("\n[B2.3] JSON Structural Trim")

    import json as _json

    # Большой JSON object
    big_obj = {f"key_{i}": {"nested": {"value": "x" * 100, "count": i}} for i in range(50)}
    big_obj_str = _json.dumps(big_obj, ensure_ascii=False)
    trimmed_obj = _json_structural_trim(big_obj_str, 500)
    check("JSON obj: smaller than max", len(trimmed_obj) <= 500,
          f"len={len(trimmed_obj)}")
    check("JSON obj: valid JSON after trim",
          _json.loads(trimmed_obj) is not None)
    check("JSON obj: preserves some keys",
          any(f"key_" in k for k in _json.loads(trimmed_obj).keys()))

    # Большой JSON array
    big_arr = [{"id": i, "name": f"item_{i}", "data": "y" * 50} for i in range(100)]
    big_arr_str = _json.dumps(big_arr, ensure_ascii=False)
    trimmed_arr = _json_structural_trim(big_arr_str, 800)
    check("JSON arr: smaller than max", len(trimmed_arr) <= 800,
          f"len={len(trimmed_arr)}")
    check("JSON arr: valid JSON after trim",
          _json.loads(trimmed_arr) is not None)
    parsed_arr = _json.loads(trimmed_arr)
    check("JSON arr: has _truncated marker",
          any("_truncated" in str(item) for item in parsed_arr))
    check("JSON arr: preserved first items",
          parsed_arr[0].get("id") == 0)

    # Маленький JSON не тримится
    small_json = '{"a": 1, "b": 2}'
    check("JSON: small unchanged",
          _json_structural_trim(small_json, 500) == small_json)

    # Невалидный JSON → fallback на head+tail
    invalid_json = '{"broken": "json' + "x" * 5000
    trimmed_invalid = _json_structural_trim(invalid_json, 500)
    check("JSON invalid: falls back to head+tail",
          len(trimmed_invalid) <= 500 + 100)
    check("JSON invalid: has СОКРАЩЕНО marker",
          "СОКРАЩЕНО" in trimmed_invalid)

    # Вложенная структура
    nested = {"level1": {"level2": {"level3": {"items": list(range(200))}}}}
    nested_str = _json.dumps(nested)
    trimmed_nested = _json_structural_trim(nested_str, 300)
    check("JSON nested: valid after trim",
          _json.loads(trimmed_nested) is not None)
    check("JSON nested: smaller than max", len(trimmed_nested) <= 300,
          f"len={len(trimmed_nested)}")

    # Интеграция через prepare_context
    padding_json = [{"role": "user", "content": "pad_" + str(i) * 200} for i in range(80)]
    msgs_json = [
        {"role": "system", "content": "sys"},
    ] + padding_json + [
        {"role": "user", "content": "get data"},
        {"role": "assistant", "content": "calling api", "tool_calls": [
            {"id": "j1", "function": {"name": "web_fetch", "arguments": '{"url":"https://api.example.com"}'}}
        ]},
        {"role": "tool", "tool_call_id": "j1", "content": big_arr_str},
    ]
    out_json, diag_json = prepare_context(msgs_json, "API")
    tool_json = [m for m in out_json if m.get("role") == "tool"]
    if tool_json:
        tc = tool_json[0].get("content", "")
        try:
            _json.loads(tc.strip())
            check("Integration: JSON result is valid JSON", True)
        except Exception as e:
            check("Integration: JSON result is valid JSON", False, f"INVALID JSON: {e}")
        check("Integration: JSON result within limit",
              len(tc) <= 3000 + 100, f"len={len(tc)}")
    else:
        check("Integration: JSON tool msg present", False, "NO TOOL MSG")

    # --- Test B2.4: Search Structural Trim ---
    print("\n[B2.4] Search Structural Trim")

    # Стандартный формат path:line:content
    search_results = "\n".join([
        f"src/module_{i}.py:{10+i}:def function_{i}(arg):" 
        for i in range(30)
    ])
    trimmed_search = _search_structural_trim(search_results, 500)
    check("Search: smaller than max", len(trimmed_search) <= 500,
          f"len={len(trimmed_search)}")
    check("Search: has metadata header",
          "Показано" in trimmed_search and "из" in trimmed_search)
    check("Search: has hidden count",
          "скрыто" in trimmed_search or "ещё" in trimmed_search)
    check("Search: preserves first results",
          "module_0.py" in trimmed_search)
    check("Search: does NOT contain late results",
          "module_29.py" not in trimmed_search)

    # Маленький поиск не тримится
    small_search = "file.py:10:def foo():\nfile.py:20:def bar():"
    check("Search: small unchanged",
          _search_structural_trim(small_search, 500) == small_search)

    # Блоковый формат (без path:line:)
    block_search = "\n\n".join([f"Result {i}:\nSome context line {i}" for i in range(20)])
    trimmed_block = _search_structural_trim(block_search, 400)
    check("Search blocks: smaller than max", len(trimmed_block) <= 400,
          f"len={len(trimmed_block)}")
    check("Search blocks: has metadata",
          "Показано" in trimmed_block or "СОКРАЩЕНЫ" in trimmed_block)

    # Интеграция через prepare_context
    padding_search = [{"role": "user", "content": "pad_" + str(i) * 200} for i in range(80)]
    big_search = "\n".join([f"brain.py:{i}:line content {i} " + "x"*50 for i in range(100)])
    msgs_search = [
        {"role": "system", "content": "sys"},
    ] + padding_search + [
        {"role": "user", "content": "find pattern"},
        {"role": "assistant", "content": "searching", "tool_calls": [
            {"id": "s1", "function": {"name": "file_search", "arguments": '{"query":"pattern","path":"."}'}}
        ]},
        {"role": "tool", "tool_call_id": "s1", "content": big_search},
    ]
    out_search, diag_search = prepare_context(msgs_search, "API")
    tool_search = [m for m in out_search if m.get("role") == "tool"]
    if tool_search:
        tc = tool_search[0].get("content", "")
        check("Integration: search result trimmed",
              len(tc) <= 3000 + 100, f"len={len(tc)}")
        check("Integration: search has metadata",
              "Показано" in tc or "СОКРАЩЕНЫ" in tc or "скрыто" in tc)
    else:
        check("Integration: search tool msg present", False, "NO TOOL MSG")

    # --- Summary ---
    print("\n" + "=" * 64)
    total = passed + failed
    print(f"  RESULTS: {passed}/{total} passed, {failed} failed")
    if failed == 0:
        print("  🎉 ALL CONTEXT MANAGER TESTS PASSED")
    else:
        print(f"  ⚠️  {failed} TESTS FAILED")
    print("=" * 64)
