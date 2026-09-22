"""
PERSONAL AI BRAIN — FACT EXTRACTOR (GATEWAY TO MEMORY 2.0)
Изолированный модуль извлечения, валидации и фильтрации устойчивых фактов.

Архитектура «Ворота Качества»:
1. Fast Heuristic Pre-Filter (отсев 95% мусора без LLM).
2. Candidate Extractor (детерминированное извлечение ядра факта от 3-го лица).
3. Stability & Noise Check (длина 20-250 символов, отсев временного контекста).
4. Deduplication & Refinement (проверка дублей и расширений без тяжелых эмбеддингов).
5. Gateway Action (SAVE_PRIMARY для явных, ENQUEUE для неявных).
"""

import re
import json
import os
import difflib
from datetime import datetime
from typing import Optional, Dict, List, Tuple, Any

CANDIDATES_PATH = "/storage/emulated/0/Documents/AI_Brain/brain_memory_candidates.json"

NOISE_WORDS = {
    "error", "traceback", "exception", "failed", "syntaxerror",
    "ls -l", "grep", "cat ", "sed -n", "python3", "bash", "termux-",
    "готов", "готово", "выполнил", "сделано", "отправь", "напиши",
    "привет", "здравствуй", "добрый день", "спасибо", "пожалуйста",
    "покажи", "прочитай файл", "дерево файлов", "статус", "модели"
}

TRANSIENT_WORDS = {
    "сейчас", "сегодня", "в данный момент", "только что", "в этой сессии",
    "в этот раз", "временно", "минуту назад", "пока что", "текущий запуск"
}


def _normalize_text(text: str) -> str:
    """Приводит текст к нормализованному виду (без знаков препинания)."""
    if not text:
        return ""
    text = text.lower().replace("ё", "е")
    # Удаляем точки, запятые и спецсимволы
    text = re.sub(r"[^\w\s\-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _get_significant_words(text: str) -> set:
    """Извлекает значимые слова (длиной от 2 символов, без стоп-слов)."""
    norm = _normalize_text(text)
    words = re.findall(r"[а-яa-z0-9\-]+", norm)
    stop = {
        "что", "это", "как", "где", "когда", "кто", "пользователь",
        "мой", "моя", "мои", "мое", "мне", "меня", "мной",
        "для", "про", "при", "через", "или", "есть", "быть", "был"
    }
    # Разрешаем слова от 2 символов (f6, 12, ram, 3b, 4b)
    return {w for w in words if len(w) >= 2 and w not in stop}


def detect_fact_candidate(user_text: str) -> Optional[Dict[str, Any]]:
    """
    Ворота 1 и 2: Детекция кандидата и классификация источника.
    Гарантированно возвращает словарь со всеми 4 полями или None.
    """
    if not user_text or len(user_text.strip()) < 8:
        return None

    stripped = user_text.strip()
    lowered = stripped.lower()

    # Быстрый отсев шума (команды, приветствия)
    if any(nw in lowered for nw in NOISE_WORDS):
        if not re.match(r"^(?:запомни|сохрани в память|зафиксируй)[:,\s]+", lowered):
            return None

    fact_text = ""
    source = "user_stated"
    confidence = 0.85
    category = "general"

    # 1. Явные директивы пользователя (EXPLICIT) -> confidence 1.0
    explicit_match = re.match(r"^(?:запомни|сохрани в память|зафиксируй)[:,\s]+(.+)$", stripped, re.IGNORECASE)
    if explicit_match:
        raw = explicit_match.group(1).strip()
        # Преобразуем глаголы 1-го лица к 3-му лицу
        raw = re.sub(r"^(?:что\s+)?я\s+пишу\b", "Пользователь пишет", raw, flags=re.IGNORECASE)
        raw = re.sub(r"^(?:что\s+)?я\s+использую\b", "Пользователь использует", raw, flags=re.IGNORECASE)
        raw = re.sub(r"^(?:что\s+)?я\s+предпочитаю\b", "Пользователь предпочитает", raw, flags=re.IGNORECASE)
        raw = re.sub(r"^(?:что\s+)?я\s+работаю\b", "Пользователь работает", raw, flags=re.IGNORECASE)
        raw = re.sub(r"^(?:что\s+)?я\s+", "Пользователь ", raw, flags=re.IGNORECASE)
        raw = re.sub(r"^(?:что\s+)?у\s+меня\s+", "У пользователя ", raw, flags=re.IGNORECASE)
        fact_text = raw
        source = "user_explicit"
        confidence = 1.0
        category = _detect_category(fact_text)

    # 2. Утверждения пользователя (STATED) -> confidence 0.85
    elif re.search(r"\b(я использую|мой телефон|моё устройство|мое устройство|моя среда|мой стек|я предпочитаю|я пишу на)\b", lowered):
        m_dev = re.search(r"(?:у меня|мой)\s+(телефон|смартфон|ноутбук|пк|девайс|стек|дистрибутив|окружение)\s+([^.,;\n]+)", stripped, re.IGNORECASE)
        if m_dev:
            fact_text = f"Пользователь использует {m_dev.group(1)} {m_dev.group(2).strip()}."
            source = "user_stated"
            confidence = 0.85
            category = "environment"
        else:
            m_pref = re.search(r"я\s+(?:использую|предпочитаю|пишу на)\s+([^.,;\n]+)", stripped, re.IGNORECASE)
            if m_pref:
                fact_text = f"Пользователь предпочитает {m_pref.group(1).strip()}."
                source = "user_stated"
                confidence = 0.85
                category = "preferences"

    if not fact_text:
        return None

    # Нормализуем регистр и точку в конце
    fact_text = fact_text[0].upper() + fact_text[1:]
    if not fact_text.endswith("."):
        fact_text += "."

    return {
        "text": fact_text,
        "category": category,
        "source": source,
        "confidence": confidence,
    }


def _detect_category(text: str) -> str:
    """Определяет базовую категорию факта."""
    t = text.lower()
    if any(w in t for w in ("телефон", "смартфон", "poco", "android", "termux", "linux", "ram", "память", "snapdragon")):
        return "environment"
    if any(w in t for w in ("python", "bash", "код", "стек", "git", "llama", "модель", "api", "аннотаци")):
        return "project_rules"
    if any(w in t for w in ("предпочита", "люблю", "стиль", "всегда", "никогда")):
        return "preferences"
    return "general"


def validate_stability(fact: Dict[str, Any]) -> Tuple[bool, str]:
    """Ворота 3: Проверка стабильности и отсутствия шума."""
    text = fact.get("text", "")
    if len(text) < 20:
        return False, "Слишком короткий факт (меньше 20 символов)"
    if len(text) > 250:
        return False, "Слишком длинный факт (больше 250 символов)"

    lowered = text.lower()
    for tw in TRANSIENT_WORDS:
        if re.search(r"\b" + re.escape(tw) + r"\b", lowered):
            return False, f"Обнаружен маркер временного контекста: '{tw}'"

    return True, "OK"


def check_duplicate_or_refinement(new_fact: Dict[str, Any], existing_entries: List[Dict[str, Any]]) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Ворота 4: Дедупликация и семантическое уточнение (Refinement).
    """
    new_text = new_fact.get("text", "")
    new_words = _get_significant_words(new_text)

    if not new_words:
        return "DUPLICATE", None

    for entry in existing_entries:
        old_text = entry.get("text", "")
        old_words = _get_significant_words(old_text)

        if not old_words:
            continue

        # 1. Сначала проверяем на семантическое уточнение (Refinement):
        # Если старый факт строго содержится в новом, и в новом появились новые подробности
        if old_words.issubset(new_words) and len(new_words) > len(old_words):
            return "REFINEMENT", entry

        # 2. Проверка на точный или лексический дубликат
        ratio = difflib.SequenceMatcher(None, _normalize_text(old_text), _normalize_text(new_text)).ratio()
        if ratio > 0.82:
            return "DUPLICATE", entry

        intersection = len(old_words & new_words)
        union = len(old_words | new_words)
        jaccard = intersection / union if union > 0 else 0.0

        if jaccard > 0.75:
            return "DUPLICATE", entry

    return "NEW", None


def process_extraction_flow(user_text: str, answer_text: str, existing_entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Главный оркестратор Ворот Качества."""
    default_res = {
        "action": "IGNORE",
        "fact": {"text": "", "category": "general", "source": "none", "confidence": 0.0},
        "reason": "",
        "target_entry_id": None
    }

    # Ворота 1 и 2
    candidate = detect_fact_candidate(user_text)
    if not candidate:
        default_res["reason"] = "Кандидат не обнаружен"
        return default_res

    # Ворота 3
    is_stable, reason = validate_stability(candidate)
    if not is_stable:
        default_res["reason"] = f"Отклонено фильтром стабильности: {reason}"
        return default_res

    # Ворота 4
    status, matched_entry = check_duplicate_or_refinement(candidate, existing_entries)
    if status == "DUPLICATE":
        default_res["reason"] = f"Дубликат существующей записи (id={matched_entry.get('id', '')[:8]})"
        return default_res

    if status == "REFINEMENT":
        return {
            "action": "UPDATE_PRIMARY",
            "fact": candidate,
            "reason": f"Уточнение существующей записи (id={matched_entry.get('id', '')[:8]})",
            "target_entry_id": matched_entry.get("id")
        }

    # Ворота 5: Определение действия
    if candidate["source"] == "user_explicit" or candidate["confidence"] >= 0.80:
        return {
            "action": "SAVE_PRIMARY",
            "fact": candidate,
            "reason": "Надежный факт пользователя",
            "target_entry_id": None
        }

    return {
        "action": "ENQUEUE",
        "fact": candidate,
        "reason": "Требует подтверждения",
        "target_entry_id": None
    }


def load_candidates() -> List[Dict[str, Any]]:
    if not os.path.exists(CANDIDATES_PATH):
        return []
    try:
        with open(CANDIDATES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("candidates", [])
    except Exception:
        return []


def save_candidate(fact: Dict[str, Any]) -> bool:
    try:
        os.makedirs(os.path.dirname(CANDIDATES_PATH), exist_ok=True)
        candidates = load_candidates()
        fact_copy = dict(fact)
        fact_copy["id"] = f"cand_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        fact_copy["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        candidates.append(fact_copy)
        with open(CANDIDATES_PATH, "w", encoding="utf-8") as f:
            json.dump({"candidates": candidates}, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def clear_candidates() -> bool:
    try:
        if os.path.exists(CANDIDATES_PATH):
            with open(CANDIDATES_PATH, "w", encoding="utf-8") as f:
                json.dump({"candidates": []}, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def approve_candidate(candidate_id: str) -> Optional[Dict[str, Any]]:
    """Убирает кандидата из очереди по id и возвращает его данные
    для сохранения в основную память. Возвращает None, если не найден."""
    candidates = load_candidates()
    match = None
    remaining = []
    for c in candidates:
        if c.get("id") == candidate_id:
            match = c
        else:
            remaining.append(c)

    if match is None:
        return None

    try:
        os.makedirs(os.path.dirname(CANDIDATES_PATH), exist_ok=True)
        with open(CANDIDATES_PATH, "w", encoding="utf-8") as f:
            json.dump({"candidates": remaining}, f, ensure_ascii=False, indent=2)
    except Exception:
        return None

    return match


if __name__ == "__main__":
    print("=" * 64)
    print("FACT EXTRACTOR — ISOLATED TEST SUITE")
    print("=" * 64)

    passed = 0
    total = 0

    def check(name: str, condition: bool):
        global passed, total
        total += 1
        if condition:
            passed += 1
            print(f"  ✅ {name}")
        else:
            print(f"  ❌ FAIL: {name}")

    existing_db = [
        {"id": "entry_1", "text": "Пользователь использует смартфон POCO F6."},
        {"id": "entry_2", "text": "Основной язык общения: русский."}
    ]

    print("\n[1] Отсев технического шума и обычных команд")
    r1 = process_extraction_flow("ls -la ~/personal_ai_brain", "ok", existing_db)
    check("Команда bash отклонена", r1["action"] == "IGNORE")

    r2 = process_extraction_flow("прочитай файл brain.py", "содержимое", existing_db)
    check("Запрос к инструменту отклонен", r2["action"] == "IGNORE")

    r3 = process_extraction_flow("Привет, как дела?", "Отлично!", existing_db)
    check("Приветствие отклонено", r3["action"] == "IGNORE")

    print("\n[2] Явные директивы пользователя")
    r4 = process_extraction_flow("запомни: я пишу весь код строго с аннотациями типов", "учту", existing_db)
    check("Явная директива принята к сохранению", r4["action"] == "SAVE_PRIMARY")
    check("Confidence == 1.0", r4["fact"]["confidence"] == 1.0)
    check("Source == user_explicit", r4["fact"]["source"] == "user_explicit")
    check("Формулировка нормализована", "Пользователь пишет весь код строго с аннотациями типов." in r4["fact"]["text"])

    print("\n[3] Утверждения о среде и стеке")
    r5 = process_extraction_flow("мой телефон Xiaomi Redmi Note 10 Pro", "понял", existing_db)
    check("Утверждение об устройстве распознано", r5["action"] == "SAVE_PRIMARY")
    check("Категория == environment", r5["fact"]["category"] == "environment")
    check("Confidence == 0.85", r5["fact"]["confidence"] == 0.85)

    print("\n[4] Фильтр стабильности (отсев временного контекста)")
    r6 = process_extraction_flow("запомни: сейчас я нахожусь на улице и тестирую связь", "ок", existing_db)
    check("Временный контекст 'сейчас' отклонен", r6["action"] == "IGNORE")
    check("Причина стабильности указана", "временного контекста" in r6["reason"])

    print("\n[5] Дедупликация и семантическое уточнение")
    r7 = process_extraction_flow("запомни: пользователь использует смартфон POCO F6", "ок", existing_db)
    check("Точный дубль отклонен", r7["action"] == "IGNORE")
    check("Причина дубля зафиксирована", "Дубликат" in r7["reason"])

    r8 = process_extraction_flow("запомни: пользователь использует смартфон POCO F6 с 12 ГБ RAM и 512 ГБ памяти", "ок", existing_db)
    check("Уточнение распознано как UPDATE_PRIMARY", r8["action"] == "UPDATE_PRIMARY")
    check("ID целевой записи совпал с entry_1", r8["target_entry_id"] == "entry_1")

    print("\n[6] Гарантия контракта полей факта")
    for key in ("text", "category", "source", "confidence"):
        check(f"Поле {key} присутствует в результате", key in r8["fact"])

    print("\n" + "=" * 64)
    print(f"RESULTS: {passed}/{total} passed, {total - passed} failed")
    if passed == total:
        print("🎉 ALL FACT EXTRACTOR TESTS PASSED")
    print("=" * 64)
