#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ============================================================
# [01] ЗАГОЛОВОК И ОПИСАНИЕ
# ============================================================

"""
PERSONAL AI BRAIN

Главная модель:
    nvidia/nemotron-3-super-120b-a12b:free

Принцип:
    только бесплатные модели

Возможности:
    - GLM-5.2 как главный приоритет
    - автоматическое определение задачи
    - автоматический fallback
    - рейтинг моделей
    - ограниченная история
    - статистика
    - определение фактической модели
    - OpenRouter Free Router
    - русский интерфейс
    - русские и английские команды

ВАЖНО:
    Для HTTP используется requests.
    urllib намеренно НЕ используется.
"""


# ============================================================
# [02] ИМПОРТЫ
# ============================================================

import logging
import os
import sys
import importlib.util
import time
import json

import requests

import verifier
import goal_verifier
import planner
import task_manager
import execution_engine
import chat_system
from input_collector import _collect_multiline_input, _collect_burst_input

from collections import defaultdict
from memory.memory_core import load_memory, add_memory, show_memory, show_all_memory, find_memory, status_memory, clear_memory, get_relevant_memory, update_memory_entry, _load_raw, delete_memory, _normalize_words, _score_entry, load_entries_for_fact_extraction, MEMORY_FILE
from memory.fact_extractor import (process_extraction_flow, load_candidates, save_candidate, approve_candidate, clear_candidates, detect_fact_candidate, CandidateQueueError, resolve_candidate_id)
from memory.read_only_audit import audit_memory
from memory.read_only_audit import audit_memory
import mcp_bridge
import tool_registry
import context_manager
import project_context
import context_personalization
import self_inspection
import module_manager
import execution_intent
import autonomy_controller
import git_readonly
import skills_manager
import tool_catalog as phase4_tool_catalog
import tool_proposals as phase4_tool_proposals
import tool_proposal_manager as phase4_proposal_manager
import tool_proposal_commands as phase4_proposal_commands

# Глобальный реестр инструментов — источник истины для схемы и безопасности
REGISTRY = tool_registry.create_default_registry()
TOOL_PROPOSAL_MANAGER = None


# ============================================================
# [03] ОСНОВНЫЕ НАСТРОЙКИ
# ============================================================

BASE_URL = "https://openrouter.ai/api/v1"

# ============================================================
# [03b] GEMINI API (прямой доступ, бесплатный tier)
# ============================================================
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODELS = {
    "gemini-3.7-flash": "gemini-3.7-flash",
    "gemini-3.6-flash": "gemini-3.6-flash",
    "gemini-3.5-flash": "gemini-3.5-flash",
    "gemini-3.5-flash-lite": "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite": "gemini-3.1-flash-lite",
    "gemini-3.8-flash": "gemini-3.8-flash",
    # Удобные короткие алиасы для ручного переключения
    "3.7-flash": "gemini-3.7-flash",
    "3.7": "gemini-3.7-flash",
    "3.6-flash": "gemini-3.6-flash",
    "3.6": "gemini-3.6-flash",
    "3.5-flash": "gemini-3.5-flash",
    "3.5": "gemini-3.5-flash",
    "3.5-lite": "gemini-3.5-flash-lite",
    "lite": "gemini-3.5-flash-lite",
    "3.1-lite": "gemini-3.1-flash-lite",
    "3.8-flash": "gemini-3.8-flash",
    "3.8": "gemini-3.8-flash",
}
GEMINI_DEFAULT_MODEL = "gemini-3.7-flash"
GEMINI_FALLBACK_CHAIN = [
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
]
GEMINI_DEFAULT_MODEL = "gemini-3.7-flash"


PRIMARY_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"

FREE_ROUTER = "openrouter/free"

# Таймаут полного запроса к модели.
# Оставляем достаточно большим для медленных Free-провайдеров.
REQUEST_TIMEOUT = 90

# Таймаут получения списка моделей.
MODELS_TIMEOUT = 30

# Сколько секунд ждать модель при обычном запросе
# до перехода к следующему кандидату.
MODEL_RESPONSE_TIMEOUT = 35

# Прогрев должен быть коротким и не резервировать полный лимит модели.
WARMUP_MAX_TOKENS = 64

# Отдельный таймаут для локальных llama-server.
# Локальные модели на смартфоне могут генерировать ответ дольше API.
LOCAL_MODEL_RESPONSE_TIMEOUT = 120

# После 429 модель временно исключается из маршрутизации.
MODEL_429_COOLDOWN = 45

# Модели, структурно неподходящие для обычного API (НЕ временный бан)
BLOCKED_MODELS = {
    "thinkingmachines/inkling:free",
    "thinkingmachines/inkling-small:free",
    "nvidia/nemotron-3.5-content-safety:free",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
}

MAX_HISTORY_API = 150
MAX_HISTORY_LOCAL = 24

MAX_CANDIDATES = 10

GLM_COOLDOWN = 60


# ============================================================
# [04] API KEY
# ============================================================

API_KEY = os.environ.get(
    "OPENROUTER_API_KEY",
    ""
).strip()

if not API_KEY:

    print()
    print("=" * 64)
    print("ОШИБКА: OPENROUTER_API_KEY не найден.")
    print("=" * 64)
    print()
    print("Проверь переменную:")
    print()
    print("echo $OPENROUTER_API_KEY")
    print()

    sys.exit(1)


# ============================================================
# [05] СОСТОЯНИЕ РОУТЕРА
# ============================================================

state = {

    "models": [],

    "active_model": None,

    "active_provider": None,

    "last_glm_failure": 0,

    "total_requests": 0,

    "successful_requests": 0,

    "failed_requests": 0,

    "model_stats": {},

    "controller_mode": "AUTO",

    "model_lock": None,

    "model_lock_type": None,

    "model_lock_layer": None
}


def load_stats():
    """
    Загружает статистику моделей с диска.
    """
    stats_file = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "router_stats.json"
    )

    if not os.path.exists(stats_file):
        return

    try:
        with open(
            stats_file,
            "r",
            encoding="utf-8"
        ) as file:
            saved = json.load(file)

        if isinstance(saved, dict):
            state["model_stats"] = saved.get(
                "model_stats",
                {}
            )

            # Миграция: добавить error_types в старые записи
            for mid, mdata in state["model_stats"].items():
                if isinstance(mdata, dict):
                    if "error_types" not in mdata:
                        mdata["error_types"] = {}
                    if "last_status_code" not in mdata:
                        mdata["last_status_code"] = None

            state["total_requests"] = saved.get(
                "total_requests",
                0
            )

            state["successful_requests"] = saved.get(
                "successful_requests",
                0
            )

            state["failed_requests"] = saved.get(
                "failed_requests",
                0
            )

    except Exception as error:
        print(
            f"⚠ Не удалось загрузить статистику: {error}"
        )


_last_stats_save_time = 0
_stats_save_interval = 30  # секунд между записями на диск
_pending_stats_write = False

BRAIN_LOG_FILE = "brain.log"


def classify_error(error_text):
    """Классифицирует ошибку в одну из категорий для Self-Diagnostic."""
    if not error_text:
        return "UNKNOWN"
    
    error_str = str(error_text)
    
    # RATE_LIMIT
    if "429" in error_str or "RATE_LIMIT" in error_str:
        return "RATE_LIMIT"
    
    # TIMEOUT
    if "TIMEOUT" in error_str:
        return "TIMEOUT"

    # SSL_ERROR
    if any(x in error_str for x in ["SSLError", "SSL_ERROR", "SSLEOFError", "[SSL:"]):
        return "SSL_ERROR"

    # NETWORK_ERROR
    if any(x in error_str for x in ["ConnectionError", "Max retries exceeded", "Connection refused", "Connection reset", "Network is unreachable", "Name or service not known"]):
        return "NETWORK_ERROR"

    # VERIFIER_ERROR
    if "VERIFIER" in error_str:
        return "VERIFIER_ERROR"
    
    # LOCAL_ERROR
    if "LOCAL_SERVER" in error_str or "LOCAL_HTTP" in error_str:
        return "LOCAL_ERROR"
    
    # SHELL_ERROR
    if "COMMAND_NOT_ALLOWED" in error_str:
        return "SHELL_ERROR"
    
    # FILE_ERROR
    if any(x in error_str for x in ["PATH_NOT_ALLOWED", "NOT_A_FILE", "READ_ERROR", "WRITE_ERROR", "FILE_ALREADY_EXISTS"]):
        return "FILE_ERROR"
    
    # PARSE_ERROR
    if "INVALID_TOOL_ARGUMENTS" in error_str or "TOOL_CALL_MISSING_NAME" in error_str:
        return "PARSE_ERROR"
    
    # TOOL_ERROR
    if "TOOL" in error_str or "TOOL_BRIDGE" in error_str:
        return "TOOL_ERROR"
    
    # API_ERROR
    if "HTTP_" in error_str:
        return "API_ERROR"
    
    # MODEL_ERROR
    if "Пустой ответ" in error_str or "empty" in error_str.lower():
        return "MODEL_ERROR"
    
    return "UNKNOWN"


def log_decision(task, layer, model_id, actual_model, ok, elapsed, error=None):
    """
    Пишет одну строку в brain.log о решении роутера.
    Не должен ронять основной поток при ошибке записи.
    """
    try:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

        if ok:
            line = (
                f"{timestamp} | OK    | task={task} | layer={layer} | "
                f"requested={model_id} | actual={actual_model} | "
                f"time={elapsed:.2f}s\n"
            )
        else:
            error_type = classify_error(error)
            line = (
                f"{timestamp} | ERROR | task={task} | layer={layer} | "
                f"requested={model_id} | error_type={error_type} | error={error}\n"
            )
            # Learning Core: подсчёт типов ошибок для маршрутизации
            try:
                if model_id:
                    m_stats = get_model_stats(model_id)
                    et = m_stats.get("error_types", {})
                    et[error_type] = et.get(error_type, 0) + 1
                    m_stats["error_types"] = et
            except Exception:
                pass

        with open(BRAIN_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)

    except Exception:
        pass


def save_stats_debounced():
    """
    Сохраняет статистику не чаще раза в _stats_save_interval секунд,
    чтобы не писать на flash-память при каждом успешном ответе.
    Финальная гарантированная запись происходит при выходе и при сбросе.
    """
    global _last_stats_save_time, _pending_stats_write

    now = time.time()

    if now - _last_stats_save_time >= _stats_save_interval:
        save_stats()
        _last_stats_save_time = now
        _pending_stats_write = False
    else:
        _pending_stats_write = True


def save_stats():
    """
    Сохраняет статистику моделей на диск.
    """
    stats_file = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "router_stats.json"
    )

    try:
        data = {
            "version": 1,
            "total_requests":
                state["total_requests"],
            "successful_requests":
                state["successful_requests"],
            "failed_requests":
                state["failed_requests"],
            "model_stats":
                state["model_stats"]
        }

        temp_file = stats_file + ".tmp"

        with open(
            temp_file,
            "w",
            encoding="utf-8"
        ) as file:
            json.dump(
                data,
                file,
                ensure_ascii=False,
                indent=2
            )

        os.replace(
            temp_file,
            stats_file
        )

    except Exception as error:
        print(
            f"⚠ Не удалось сохранить статистику: {error}"
        )


def get_model_stats(model_id):
    """
    Безопасно получить статистику конкретной модели.
    """

    if model_id not in state["model_stats"]:

        state["model_stats"][model_id] = {
            "success": 0,
            "fail": 0,
            "total_time": 0.0,
            "rate_429": 0,
            "cooldown_until": 0,
            "last_error": None,
            "error_types": {},
            "empty_streak": 0,
            "empty_cooldown_until": 0,
            "last_status_code": None
        }

    return state["model_stats"][model_id]


# ============================================================


# [06] HTTP GET — СПИСОК МОДЕЛЕЙ
# ============================================================

def get_models_api():

    """
    Получение списка моделей.

    Авторизация здесь НЕ нужна.
    Используем requests.
    """

    url = BASE_URL + "/models"

    try:

        response = requests.get(
            url,
            timeout=MODELS_TIMEOUT,
            headers={
                "Accept": "application/json"
            }
        )

        return response

    except requests.RequestException as error:

        print()
        print(
            "Ошибка соединения с OpenRouter:"
        )

        print(
            str(error)
        )

        return None


# ============================================================
# [07] ПОЛУЧЕНИЕ FREE-МОДЕЛЕЙ
# ============================================================

FREE_MODELS_CACHE = []


def get_free_models(force_refresh=False):

    global FREE_MODELS_CACHE

    if FREE_MODELS_CACHE and not force_refresh:

        return FREE_MODELS_CACHE

    print()
    print(
        "Получаю актуальные бесплатные модели..."
    )

    response = get_models_api()

    if response is None:

        return []

    if response.status_code != 200:

        print(
            f"OpenRouter HTTP {response.status_code}"
        )

        return []

    try:

        data = response.json()

    except Exception as error:

        print(
            "Ошибка JSON:",
            error
        )

        return []

    models = data.get(
        "data",
        []
    )

    free_models = []

    for model in models:

        model_id = str(
            model.get(
                "id",
                ""
            )
        )

        if not model_id.endswith(
            ":free"
        ):

            continue

        pricing = model.get(
            "pricing",
            {}
        )

        prompt = str(
            pricing.get(
                "prompt",
                ""
            )
        )

        completion = str(
            pricing.get(
                "completion",
                ""
            )
        )

        try:

            prompt_zero = (
                float(prompt) == 0
            )

            completion_zero = (
                float(completion) == 0
            )

        except Exception:

            prompt_zero = False
            completion_zero = False

        if (
            prompt_zero
            and completion_zero
        ):

            free_models.append(
                model
            )

    state["models"] = free_models

    
    # Добавляем Gemini (прямой API, бесплатный tier) если ключ есть
    if GEMINI_API_KEY:
        for gemini_id in GEMINI_MODELS:
            # Проверяем, что ещё не добавлена
            if not any(m.get("id") == gemini_id for m in free_models):
                free_models.append({
                    "id": gemini_id,
                    "name": f"Gemini ({gemini_id})",
                    "provider": "google",
                    "layer": "GEMINI",
                    "context_length": 1000000,
                    "pricing": {"prompt": "0", "completion": "0"},
                })

    FREE_MODELS_CACHE = free_models

    return FREE_MODELS_CACHE


# ============================================================
# [08] ОПРЕДЕЛЕНИЕ ТИПА ЗАДАЧИ
# ============================================================

def detect_task(text):

    text = text.lower()

    def has_keyword(word):
        if word == "бот":
            import re
            return bool(
                re.search(
                    r"(?<![а-яёa-z0-9])бот(?![а-яёa-z0-9])",
                    text,
                    re.IGNORECASE
                )
            )

        if word.isascii() and word.isalpha():
            import re
            return bool(
                re.search(
                    rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])",
                    text,
                    re.IGNORECASE
                )
            )

        return word in text

    code_words = [
        "python",
        "javascript",
        "typescript",
        "java",
        "c++",
        "c#",
        "html",
        "css",
        "sql",
        "bash",
        "shell",
        "termux",
        "telegram bot",
        "telegram-бот",
        "телеграм бот",
        "бот",
        "api",
        "json",
        "github",
        "git",
        "код",
        "скрипт",
        "программа",
        "программирование",
        "отлад",
        "debug"
    ]

    reasoning_words = [
        "проанализируй",
        "анализ",
        "сравни",
        "сравнение",
        "почему",
        "причина",
        "стратегия",
        "рассуждение",
        "логика",
        "реши",
        "решение",
        "разбери",
        "исследуй",
        "пошагово"
    ]

    data_words = [
        "data",
        "данные",
        "dataset",
        "датасет",
        "pandas",
        "numpy",
        "excel",
        "csv",
        "таблиц",
        "database",
        "база данных",
        "machine learning",
        "машинное обучение",
        "ml"
    ]

    writing_words = [
        "напиши письмо",
        "сообщение",
        "отклик",
        "резюме",
        "пост",
        "статья",
        "описание",
        "перепиши",
        "исправь текст",
        "сделай текст",
        "переведи",
        "перевод"
    ]

    creative_words = [
        "стих",
        "стихотворение",
        "рассказ",
        "история",
        "сценарий",
        "песня",
        "придумай",
        "креатив",
        "сюжет"
    ]

    if any(
        has_keyword(word)
        for word in code_words
    ):

        return "code"

    if any(
        has_keyword(word)
        for word in data_words
    ):

        return "data"

    if any(
        has_keyword(word)
        for word in reasoning_words
    ):

        return "reasoning"

    if any(
        has_keyword(word)
        for word in writing_words
    ):

        return "writing"

    if any(
        has_keyword(word)
        for word in creative_words
    ):

        return "creative"

    return "general"


# ============================================================
# [09] РЕЙТИНГ МОДЕЛИ
# ============================================================

def score_model(model, task):

    model_id = str(
        model.get(
            "id",
            ""
        )
    ).lower()

    description = str(
        model.get(
            "description",
            ""
        )
    ).lower()

    context = model.get(
        "context_length",
        0
    ) or 0

    score = 0

    # Приоритет текущей главной модели (PRIMARY_MODEL)
    if (
        model.get("id")
        == PRIMARY_MODEL
    ):

        score += 1_000_000

    # Сильные модели
    strong_words = [
        "gpt-oss",
        "qwen3",
        "deepseek",
        "minimax",
        "nemotron",
        "kimi",
        "mistral"
    ]

    for word in strong_words:

        if word in model_id:

            score += 10_000

    # Код — сильный приоритет специализированных моделей.
    if task == "code":

        for word in [
            "coder",
            "coding",
            "code",
            "programming",
            "agent"
        ]:

            if word in model_id:
                score += 20_000

            if word in description:
                score += 5_000

    # Reasoning — сильный приоритет специализированных моделей.
    if task == "reasoning":

        for word in [
            "reasoning",
            "think",
            "math",
            "agent"
        ]:

            if word in model_id:
                score += 20_000

            if word in description:
                score += 5_000

    # Data — сильный приоритет моделей для данных и исследований.
    if task == "data":

        for word in [
            "reasoning",
            "data",
            "research",
            "agent",
            "math"
        ]:

            if word in model_id:
                score += 20_000

            if word in description:
                score += 5_000

    # Большой контекст
    if context >= 1_000_000:

        score += 1_000

    elif context >= 500_000:

        score += 700

    elif context >= 200_000:

        score += 400

    elif context >= 100_000:

        score += 200

    # История успеха
    stats = state[
        "model_stats"
    ].get(
        model.get("id"),
        {}
    )

    success = stats.get(
        "success",
        0
    )

    fail = stats.get(
        "fail",
        0
    )

    total_time = stats.get(
        "total_time",
        0.0
    )

    # История влияет на рейтинг постепенно.
    # Успех повышает доверие, но не делает модель фаворитом после одного ответа.
    score += success * 50

    # Ошибка сильнее успеха снижает доверие.
    score -= fail * 75

    # Learning Core: разные типы ошибок имеют разный вес
    error_types = stats.get("error_types", {})
    # Ошибки модели — сильно снижают рейтинг
    score -= error_types.get("MODEL_ERROR", 0) * 50
    score -= error_types.get("TIMEOUT", 0) * 40
    score -= error_types.get("API_ERROR", 0) * 30
    # Ошибки парсинга — частично вина модели
    score -= error_types.get("PARSE_ERROR", 0) * 25
    # Ошибки инструментов/верификатора — не вина модели, минимальный штраф
    score -= error_types.get("VERIFIER_ERROR", 0) * 5
    score -= error_types.get("TOOL_ERROR", 0) * 5
    score -= error_types.get("SHELL_ERROR", 0) * 5
    score -= error_types.get("FILE_ERROR", 0) * 5

    # 429 дополнительно снижает доверие к модели.
    rate_429 = stats.get(
        "rate_429",
        0
    )

    score -= rate_429 * 150

    # --------------------------------------------------------
    # АДАПТИВНАЯ СКОРОСТЬ
    # --------------------------------------------------------
    # Используем среднее время только после успешных запросов.
    # Чем быстрее модель, тем больше бонус.
    if success > 0 and total_time > 0:

        avg_time = total_time / success

        if avg_time <= 5:
            score += 500

        elif avg_time <= 10:
            score += 400

        elif avg_time <= 20:
            score += 300

        elif avg_time <= 30:
            score += 200

        elif avg_time <= 45:
            score += 100

    return score


# ============================================================
# [10] ФОРМИРОВАНИЕ СПИСКА КАНДИДАТОВ
# ============================================================

def rank_models(task):

    models = get_free_models()

    if not models:

        return []

    ranked = []

    for model in models:

        model_id = model.get(
            "id",
            ""
        )

        # Любая модель временно исключается после 429
        stats = state[
            "model_stats"
        ].get(
            model_id,
            {}
        )

        # Исключаем структурно неподходящие модели
        if model_id in BLOCKED_MODELS:
            continue

        # Модели с неработающим tools-роутингом (TTL 1ч после ошибки) — вне выбора
        if stats.get("tools_unsupported_until", 0) > time.time():
            continue

        # Модели с активным empty-cooldown — вне выбора
        if stats.get("empty_cooldown_until", 0) > time.time():
            continue

        cooldown_until = stats.get(
            "cooldown_until",
            0
        )

        if cooldown_until > time.time():

            remaining = max(
                0,
                int(
                    cooldown_until
                    - time.time()
                )
            )

            continue

        score = score_model(
            model,
            task
        )

        ranked.append(
            (
                score,
                model
            )
        )

    ranked.sort(
        key=lambda item: item[0],
        reverse=True
    )

    return [
        model
        for score, model
        in ranked
    ][:MAX_CANDIDATES]


# ============================================================
# [11] ЗАПРОС К AI-МОДЕЛИ
# ============================================================


def _http_error_diagnostics(response, gateway):
    """Return bounded, non-secret HTTP error details for model routing diagnostics."""
    details = {"provider": gateway}
    body = None
    try:
        body = response.json()
    except Exception:
        pass

    error_data = body.get("error", body) if isinstance(body, dict) else None
    if isinstance(error_data, dict):
        message = error_data.get("message")
        status = error_data.get("status")
        code = error_data.get("code")
        if message:
            details["detail"] = str(message)[:500]
        if status:
            details["provider_status"] = str(status)[:120]
        if code is not None:
            details["provider_code"] = str(code)[:80]

        metadata = error_data.get("metadata")
        if isinstance(metadata, dict):
            for source_key, target_key, limit in (
                ("provider_name", "upstream_provider", 120),
                ("limit_source", "limit_source", 120),
                ("retry_after_seconds", "retry_after_seconds", 40),
            ):
                value = metadata.get(source_key)
                if value is not None and isinstance(value, (str, int, float)):
                    details[target_key] = str(value)[:limit]

            # OpenRouter may put the upstream provider's raw rejection here,
            # while error.message only contains a generic gateway summary.
            upstream_detail = metadata.get("raw") or metadata.get("provider_message")
            if upstream_detail is not None:
                details["upstream_detail"] = str(upstream_detail)[:500]

    headers = getattr(response, "headers", {})
    try:
        retry_after = headers.get("Retry-After")
    except Exception:
        retry_after = None
    if isinstance(retry_after, (str, int, float)) and "retry_after_seconds" not in details:
        details["retry_after_seconds"] = str(retry_after)[:40]

    if "detail" not in details:
        response_text = getattr(response, "text", "")
        if isinstance(response_text, str) and response_text:
            details["detail"] = response_text[:500]

    return details


def _controller_attempt_record(layer, requested_model, result):
    """Normalize one failed model attempt without discarding provider diagnostics."""
    record = {
        "layer": layer,
        "model": result.get("model") or requested_model,
        "error": result.get("error", "MODEL_REQUEST_FAILED"),
        "provider": result.get("provider") or (
            "Google Gemini" if layer == "GEMINI" else
            "OpenRouter" if layer == "API" else layer
        ),
    }
    for key in (
        "upstream_provider",
        "detail",
        "upstream_detail",
        "provider_status",
        "provider_code",
        "limit_source",
        "retry_after_seconds",
    ):
        if result.get(key) is not None:
            record[key] = result[key]
    return record


def _format_execution_model_error(result):
    """Format a concise user-facing summary of a failed analysis/plan request."""
    parts = [str(result.get("error", "MODEL_REQUEST_FAILED"))]
    for key, label in (
        ("model", "модель"),
        ("provider", "канал"),
        ("upstream_provider", "провайдер"),
        ("detail", "причина"),
        ("upstream_detail", "ответ провайдера"),
    ):
        value = result.get(key)
        if value:
            parts.append(f"{label}={str(value)[:300]}")

    attempts = result.get("attempts") or []
    if attempts:
        summaries = []
        for attempt in attempts[:6]:
            item = f'{attempt.get("model", "?")} [{attempt.get("provider", attempt.get("layer", "?"))}]'
            item += f' → {attempt.get("error", "ошибка")}'
            if attempt.get("upstream_provider"):
                item += f' ({attempt["upstream_provider"]})'
            if attempt.get("detail"):
                item += f': {str(attempt["detail"])[:160]}'
            if attempt.get("upstream_detail"):
                item += f' [upstream: {str(attempt["upstream_detail"])[:160]}]'
            summaries.append(item)
        if len(attempts) > 6:
            summaries.append(f"+ ещё {len(attempts) - 6}")
        parts.append("попытки: " + "; ".join(summaries))
    return " | ".join(parts)


def ask_gemini_model(model_id, messages, tools=None, max_tokens=None):
    """Запрос к Gemini API напрямую через OpenAI-совместимый эндпоинт."""
    if not GEMINI_API_KEY:
        return False, {"error": "GEMINI_API_KEY не установлен"}

    # Преобразуем model_id в реальное имя модели Gemini
    actual_model = GEMINI_MODELS.get(model_id, model_id)

    url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"

    headers = {
        "Authorization": f"Bearer {GEMINI_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": actual_model,
        "messages": messages,
        "stream": False,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if tools:
        payload["tools"] = tools

    started = time.time()
    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=MODEL_RESPONSE_TIMEOUT,
        )
        elapsed = time.time() - started

        stats = get_model_stats(model_id)

        # ----------------------------------------------------
        # ЛИМИТ ЗАПРОСОВ (429) И ПЕРЕГРУЗКА (503) - cooldown и сброс lock
        # ----------------------------------------------------
        if response.status_code in (429, 503):
            stats["fail"] += 1
            err_code = f"HTTP_{response.status_code}"
            if response.status_code == 429:
                stats["rate_429"] = stats.get("rate_429", 0) + 1
            else:
                stats["fail_503"] = stats.get("fail_503", 0) + 1

            stats["last_error"] = err_code
            stats["cooldown_until"] = time.time() + MODEL_429_COOLDOWN

            if state.get("model_lock") == model_id:
                state["model_lock"] = None
                state["model_lock_type"] = None
                state["model_lock_layer"] = None
                print(f"  🔓 Сброшен model_lock с {model_id} из-за {err_code}")

            return False, {
                "error": err_code,
                "time": elapsed,
                "model": model_id,
                **_http_error_diagnostics(response, "Google Gemini"),
            }

        # ----------------------------------------------------
        # СЕРВЕРНЫЕ ОШИБКИ (5xx, кроме 503)
        # ----------------------------------------------------
        if response.status_code >= 500:
            stats["fail"] += 1
            stats["last_error"] = f"HTTP_{response.status_code}"
            return False, {
                "error": f"HTTP_{response.status_code}",
                "time": elapsed,
                "model": model_id,
                **_http_error_diagnostics(response, "Google Gemini"),
            }

        # Tools-несовместимость роутинга: провайдер не принимает tools для модели
        # (перманентное свойство роутинга на момент запроса) — мягкий флаг TTL 1ч
        if response.status_code == 400 and "tool use" in (response.text or "").lower():
            stats["fail"] += 1
            stats["tools_unsupported_until"] = time.time() + 3600
            stats["last_error"] = "TOOLS_NOT_SUPPORTED"
            if state.get("model_lock") == model_id:
                state["model_lock"] = None
                print(f"  🔓 Сброшен model_lock с {model_id} (no tools support)")
            return False, {
                "error": "TOOLS_NOT_SUPPORTED",
                "time": elapsed,
                "model": model_id,
            }

        if response.status_code != 200:
            stats["fail"] += 1
            stats["last_error"] = f"HTTP_{response.status_code}"
            return False, {
                "error": f"HTTP_{response.status_code}",
                "time": elapsed,
                "model": model_id,
            }

        try:
            data = response.json()
        except Exception:
            return False, {
                "error": "Gemini вернул некорректный JSON",
                "time": elapsed,
                "model": model_id,
            }

        # ----------------------------------------------------
        # УСПЕХ: плоский контракт Brain
        # ----------------------------------------------------
        choices = data.get("choices", [])
        if not choices:
            stats["fail"] += 1
            stats["empty_streak"] = stats.get("empty_streak", 0) + 1
            if stats["empty_streak"] >= 2:
                stats["empty_cooldown_until"] = time.time() + 1800
                stats["last_error"] = "EMPTY_STREAK_COOLDOWN"
            return False, {
                "error": "Пустой ответ модели",
                "time": elapsed,
                "model": model_id,
            }

        message = choices[0].get("message", {})
        answer = message.get("content", "") or ""
        tool_calls = message.get("tool_calls", None)

        if not answer and not tool_calls:
            stats["fail"] += 1
            stats["empty_streak"] = stats.get("empty_streak", 0) + 1
            if stats["empty_streak"] >= 2:
                stats["empty_cooldown_until"] = time.time() + 1800
                stats["last_error"] = "EMPTY_STREAK_COOLDOWN"
            return False, {
                "error": "Пустой ответ модели",
                "time": elapsed,
                "model": model_id,
            }

        stats["success"] += 1
        stats["total_time"] += elapsed
        stats["empty_streak"] = 0
        return True, {
            "answer": answer,
            "model": data.get("model", model_id),
            "provider": "Google Gemini",
            "time": elapsed,
            "tool_calls": tool_calls,
        }

    except requests.exceptions.Timeout:
        return False, {"error": "TIMEOUT", "time": time.time() - started, "model": model_id}
    except Exception as e:
        return False, {"error": str(e)[:200], "time": time.time() - started, "model": model_id}

def ask_model(
    model_id,
    messages,
    tools=None,
    max_tokens=None
):

    url = (
        BASE_URL
        + "/chat/completions"
    )

    payload = {

        "model": model_id,

        "messages": messages,

        "stream": False
    }

    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    if tools:
        payload["tools"] = tools

    headers = {

        "Authorization":
            "Bearer " + API_KEY,

        "Content-Type":
            "application/json",

        "Accept":
            "application/json"
    }

    started = time.time()

    response = None
    last_error = None

    for attempt in range(2):

        try:

            response = requests.post(

                url,

                headers=headers,

                json=payload,

                timeout=MODEL_RESPONSE_TIMEOUT
            )

            break

        except requests.Timeout:

            last_error = "TIMEOUT"

        except requests.RequestException as error:

            last_error = str(error)

    if response is None:

        elapsed = (
            time.time()
            - started
        )

        return False, {

            "error":
                last_error,

            "time":
                elapsed
        }

    elapsed = (
        time.time()
        - started
    )

    # --------------------------------------------------------
    # УСПЕХ
    # --------------------------------------------------------
    # RATE LIMIT (429) - cooldown
    # --------------------------------------------------------

    if response.status_code == 429:

        stats = get_model_stats(model_id)

        stats["rate_429"] += 1
        stats["cooldown_until"] = time.time() + MODEL_429_COOLDOWN
        stats["last_error"] = "429_RATE_LIMIT"
        stats["last_status_code"] = 429

        # Сбрасываем lock при 429, чтобы controller_route выбрал другую модель
        if state.get("model_lock") == model_id:
            state["model_lock"] = None
            state["model_lock_type"] = None
            state["model_lock_layer"] = None

        return False, {
            "error": "429",
            "time": elapsed,
            "model": model_id,
            **_http_error_diagnostics(response, "OpenRouter"),
        }

    # --------------------------------------------------------
    # СЕРВЕРНЫЕ ОШИБКИ (5xx)
    # --------------------------------------------------------

    if response.status_code >= 500:

        stats = get_model_stats(model_id)

        stats["fail"] += 1
        stats["last_error"] = f"HTTP_{response.status_code}"
        stats["last_status_code"] = response.status_code

        return False, {
            "error": f"HTTP_{response.status_code}",
            "time": elapsed,
            "model": model_id,
            **_http_error_diagnostics(response, "OpenRouter"),
        }

    # --------------------------------------------------------
    # УСПЕХ
    # --------------------------------------------------------

    if response.status_code == 200:

        try:

            data = response.json()

        except Exception:

            return False, {

                "error":
                    "OpenRouter вернул некорректный JSON",

                "time":
                    elapsed
            }

        choices = data.get(
            "choices",
            []
        )

        if not choices:

            return False, {

                "error":
                    "Пустой ответ модели",

                "time":
                    elapsed
            }

        message = choices[0].get(
            "message",
            {}
        )

        answer = message.get(
            "content",
            ""
        )

        tool_calls = message.get(
            "tool_calls",
            None
        )

        if not answer and not tool_calls:

            # Повторные попытки при пустом ответе (холодный старт)
            for retry_attempt in range(1):

                try:
                    time.sleep(2 + retry_attempt)  # нарастающая пауза

                    retry_response = requests.post(
                        url,
                        headers=headers,
                        json=payload,
                        timeout=MODEL_RESPONSE_TIMEOUT
                    )

                    if retry_response.status_code == 200:

                        retry_data = retry_response.json()
                        retry_choices = retry_data.get("choices", [])

                        if retry_choices:

                            retry_message = retry_choices[0].get("message", {})
                            retry_answer = retry_message.get("content", "")

                            if retry_answer:

                                answer = retry_answer
                                tool_calls = retry_message.get("tool_calls", None)
                                data = retry_data
                                break  # успешный повтор, выходим из цикла

                except Exception:
                    pass

                if answer or tool_calls:
                    break  # получили ответ, выходим

            if not answer and not tool_calls:

                # Фиксация серии пустых ответов
                stats = get_model_stats(model_id)
                stats["empty_streak"] = stats.get("empty_streak", 0) + 1

                if stats["empty_streak"] >= 2:
                    stats["empty_cooldown_until"] = time.time() + 1800
                    stats["last_error"] = "EMPTY_STREAK_COOLDOWN"

                return False, {

                    "error":
                        "Модель вернула пустой ответ",

                    "time":
                        elapsed
                }

        # ФАКТИЧЕСКАЯ модель
        actual_model = data.get(
            "model",
            model_id
        )

        # ФАКТИЧЕСКИЙ провайдер
        provider = data.get(
            "provider",
            "OpenRouter"
        )

        # Сброс серии пустых ответов при успехе
        stats = get_model_stats(model_id)
        stats["empty_streak"] = 0
        stats["last_status_code"] = 200

        return True, {

            "answer":
                answer,

            "model":
                actual_model,

            "provider":
                provider,

            "time":
                elapsed,

            "tool_calls":
                tool_calls
        }

    # --------------------------------------------------------
    # 429
    # --------------------------------------------------------

    if response.status_code == 429:
        # ----------------------------------------------------
        # OPENROUTER 429 DIAGNOSTICS
        # ----------------------------------------------------
        # Передаём наверх реальную причину лимита:
        # retry_after, limit_source и provider.
        try:
            data = response.json()
            error_data = data.get("error", {})
            metadata = error_data.get("metadata", {})

            retry_after = metadata.get(
                "retry_after_seconds",
                metadata.get("retry_after_seconds_raw", 5)
            )

            try:
                retry_after = int(retry_after)
            except (TypeError, ValueError):
                retry_after = 5

            limit_source = metadata.get(
                "limit_source"
            )

            provider = metadata.get(
                "provider_name"
            )

        except Exception:
            retry_after = 5
            limit_source = None
            provider = None

        return False, {
            "error": "429",
            "retry_after": retry_after,
            "limit_source": limit_source,
            "provider": provider,
            "time": elapsed
        }

    # --------------------------------------------------------
    # ДРУГАЯ ОШИБКА
    # --------------------------------------------------------

    try:

        data = response.json()

        error = data.get(
            "error",
            {}
        )

        message = error.get(
            "message",
            f"HTTP {response.status_code}"
        )

    except Exception:

        message = (
            f"HTTP {response.status_code}"
        )

    stats = get_model_stats(model_id)
    stats["last_status_code"] = response.status_code

    return False, {

        "error":
            message,

        "time":
            elapsed
    }


def ask_warmup_model(route, messages):
    """Send a bounded warmup request through its declared provider layer."""
    if not isinstance(route, dict):
        return False, {"error": "WARMUP_INVALID_ROUTE"}

    model_id = str(route.get("model") or "").strip()
    layer = str(route.get("layer") or "API").strip().upper()

    if not model_id:
        return False, {"error": "WARMUP_NO_MODEL"}

    if layer == "API":
        # Never let startup warmup accidentally spend credits on a paid model.
        if model_id != FREE_ROUTER and not model_id.endswith(":free"):
            return False, {
                "error": "WARMUP_SKIPPED_NON_FREE_MODEL",
                "model": model_id,
                "layer": layer,
            }
        return ask_model(
            model_id,
            messages,
            max_tokens=WARMUP_MAX_TOKENS,
        )

    if layer == "GEMINI":
        return ask_gemini_model(
            model_id,
            messages,
            max_tokens=WARMUP_MAX_TOKENS,
        )

    # LOCAL and unknown layers are not sent to the OpenRouter endpoint.
    return False, {
        "error": f"WARMUP_UNSUPPORTED_LAYER:{layer}",
        "model": model_id,
        "layer": layer,
    }


# ============================================================
# [12] ИСТОРИЯ ДИАЛОГА
# ============================================================

HISTORY_SUM_MIN_MSGS = 4
HISTORY_SUM_INPUT_CHARS = 1000  # RU-плотность ~2-2.5 симв/токен: <=500 токенов + инструкция + генерация < n_ctx 1024; измерение 2026-09-14
HISTORY_SUM_MAX_CHARS = 600
HISTORY_SUM_TIMEOUT = 90
HISTORY_SUMMARY_ENABLED = False  # STOP 2026-09-14: RU-ввод 1000 симв не уложился в 90с (факт, не оценка); включить после решения о подходе: фон/другая модель/железо   # измерено на этом железе: 33-51s (probe 2026-09-14), запас x2

def _summarize_discarded(discarded):
    """Сжимает вытесненный фрагмент истории через локальную модель.
    Возвращает строку-сводку или None. Никогда не бросает исключений,
    диалог блокируется не дольше HISTORY_SUM_TIMEOUT секунд."""
    try:
        if len(discarded) < HISTORY_SUM_MIN_MSGS:
            return None
        svc = get_local_model_for_task("general")
        if not svc:
            return None
        print("  🧠 Суммаризация вытесненного контекста (локальная модель, до ~90с)…")
        parts = []
        total = 0
        for m in reversed(discarded):
            c = m.get("content") or ""
            if not isinstance(c, str):
                continue
            parts.append(m.get("role") + ": " + c)
            total += len(c) + 16
            if total >= HISTORY_SUM_INPUT_CHARS:
                break
        text = "\n".join(reversed(parts))[-HISTORY_SUM_INPUT_CHARS:]
        prompt = (
            "Сожми следующий фрагмент диалога в краткую сводку (до 500 символов). "
            "Сохрани только факты, решения и договорённости. "
            "Выведи только сводку, без комментариев:\n\n" + text
        )
        r = requests.post(
            svc["url"] + "/v1/chat/completions",
            json={
                "model": svc["model"],
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            },
            timeout=HISTORY_SUM_TIMEOUT,
        )
        if r.status_code != 200:
            return None
        content = (r.json().get("choices") or [{}])[0].get("message", {}).get("content", "")
        content = (content or "").strip()
        return content[:HISTORY_SUM_MAX_CHARS] or None
    except Exception as e:
        print(f"  ⚠️ Суммаризация не выполнена: {type(e).__name__}: {str(e)[:120]}")
        return None

def trim_history(messages, allow_summary=False):
    """Обрезает историю, сохраняя system prompt и не разрывая tool пары.
    Суммаризация вытесненного — ТОЛЬКО для LOCAL-путей при allow_summary=True;
    при False (default) поведение байт-в-байт прежнее: суммаризатор не вызывается,
    API/OpenRouter/Gemini-сессии гарантированно не затрагиваются."""
    if len(messages) <= MAX_HISTORY_API:
        return

    # system-сообщения; прошлые сводки (name=history_summary) в system не держим —
    # их заменит новая (каскадное сжатие). Без сводок поведение идентично старому.
    system_msgs = [m for m in messages if m.get("role") == "system" and m.get("name") != "history_summary"]
    non_system = [m for m in messages if not (m.get("role") == "system" and m.get("name") != "history_summary")]

    if len(non_system) <= MAX_HISTORY_API - len(system_msgs):
        return

    # Обрезаем non-system сообщения
    limit = MAX_HISTORY_API - len(system_msgs)
    cut_point = len(non_system) - limit

    # Не разрываем tool пары: если обрезаем в середину, сдвигаем назад
    # Tool пара: assistant с tool_calls → последующие tool сообщения
    while cut_point > 0 and cut_point < len(non_system):
        msg = non_system[cut_point]
        # Если текущее сообщение — tool response, а предыдущее — assistant с tool_calls
        if msg.get("role") == "tool":
            cut_point -= 1
            continue
        # Если предыдущее сообщение — assistant с tool_calls, а мы режем перед tool
        if cut_point > 0 and non_system[cut_point - 1].get("tool_calls"):
            cut_point -= 1
            continue
        break

    # Суммаризация вытесненного: ТОЛЬКО при allow_summary=True (LOCAL-путь).
    # Default False: суммаризатор не вызывается, поведение байт-в-байт прежнее.
    discarded = non_system[:cut_point]
    summary_text = _summarize_discarded(discarded) if (allow_summary and HISTORY_SUMMARY_ENABLED) else None

    kept = non_system[cut_point:]
    if summary_text:
        kept.insert(0, {
            "role": "system",
            "name": "history_summary",
            "content": "Сводка вытесненного диалога: " + summary_text,
        })

    trimmed = system_msgs + kept
    messages.clear()
    messages.extend(trimmed)


# ============================================================
# [13] КОМАНДА «МОДЕЛИ»
# ============================================================

import io as _io
import contextlib as _contextlib

def show_models():
    _buf = _io.StringIO()
    with _contextlib.redirect_stdout(_buf):
        _show_models_impl()
    _text = _buf.getvalue()
    print(_text, end="")
    return _text


def _show_models_impl():

    models = get_free_models(force_refresh=True)

    print()

    if not models:

        print(
            "Не удалось получить список Free-моделей."
        )

        print(
            "OpenRouter Free Router остаётся резервом."
        )

        return

    print("=" * 64)

    print(
        f"АКТУАЛЬНЫЕ БЕСПЛАТНЫЕ МОДЕЛИ: {len(models)}"
    )

    print("=" * 64)

    models.sort(
        key=lambda model:
            0
            if model.get("id")
            == PRIMARY_MODEL
            else 1
    )

    for number, model in enumerate(
        models,
        1
    ):

        model_id = model.get(
            "id",
            "unknown"
        )

        context = model.get(
            "context_length",
            0
        ) or 0

        if context >= 1_000_000:

            context_text = (
                f"{context / 1_000_000:.1f}M"
            )

        elif context >= 1_000:

            context_text = (
                f"{context / 1_000:.0f}K"
            )

        else:

            context_text = str(
                context
            )

        if model_id == PRIMARY_MODEL:

            marker = " ★ ГЛАВНЫЙ"

        else:

            marker = ""

        stats = get_model_stats(model_id)

        success = stats.get(
            "success",
            0
        )

        fail = stats.get(
            "fail",
            0
        )

        rate_429 = stats.get(
            "rate_429",
            0
        )

        total_time = stats.get(
            "total_time",
            0.0
        )

        total_done = success + fail

        if success > 0:
            avg_time = total_time / success
            avg_text = f"{avg_time:.1f}s"
        else:
            avg_text = "-"

        # --- Статус модели ---
        now = time.time()

        cooldown_until = stats.get("cooldown_until", 0)
        tools_unsupported_until = stats.get("tools_unsupported_until", 0)
        empty_cooldown_until = stats.get("empty_cooldown_until", 0)

        cooldown_ttl = max(0, int(cooldown_until - now)) if cooldown_until > now else 0
        tools_ttl = max(0, int(tools_unsupported_until - now)) if tools_unsupported_until > now else 0
        empty_ttl = max(0, int(empty_cooldown_until - now)) if empty_cooldown_until > now else 0

        if tools_ttl > 0:
            availability = f"🔴 UNAVAILABLE (TOOLS_NOT_SUPPORTED, {tools_ttl}s)"
        elif empty_ttl > 0:
            availability = f"🔴 UNAVAILABLE (EMPTY_STREAK_COOLDOWN, {empty_ttl}s)"
        elif cooldown_ttl > 0:
            _reason = stats.get("last_error") or "429"
            availability = f"🔴 UNAVAILABLE ({_reason}, {cooldown_ttl}s)"
        elif success == 0 and fail == 0:
            availability = "⚪ NOT_CHECKED"
        elif success > 0:
            availability = "🟢 READY"
        else:
            availability = "⚪ NOT_CHECKED"

        print(
            f"{number:2}. "
            f"{model_id} "
            f"[{context_text}]"
            f"{marker}"
        )

        print(
            f"    {availability} "
            f"OK:{success} "
            f"ERR:{fail} "
            f"429:{rate_429} "
            f"AVG:{avg_text}"
        )

    print("=" * 64)


# ============================================================
# [14] СТАТУС И РЕЙТИНГ
# ============================================================

def show_status():

    print()

    print("=" * 64)

    print(
        "                    СОСТОЯНИЕ РОУТЕРА"
    )

    print("=" * 64)

    print(
        f"Главная модель : {PRIMARY_MODEL}"
    )

    _status_model_names = {
        "nvidia/nemotron-3-super-120b-a12b:free": "Nemotron 3 Super",
        "nvidia/nemotron-3-super-120b-a12b": "Nemotron 3 Super",
        "/storage/emulated/0/модели/Qwen3-4B-Instruct-2507-Q4_K_M.gguf": "Qwen 3 4B",
        "/storage/emulated/0/модели/Qwen2.5-3B-Instruct.Q4_K_M.gguf": "Qwen 2.5 3B",
    }
    _active_model_raw = state["active_model"] or "нет"
    _active_model_display = (
        _status_model_names.get(_active_model_raw)
        or _active_model_raw.split("/")[-1].replace(":free", "")
    )
    print(f"Активная модель: {_active_model_display}")

    print(
        "Провайдер      : "
        + str(
            state["active_provider"]
            or "неизвестен"
        )
    )

    print(
        f"Запросов       : "
        f"{state['total_requests']}"
    )

    print(
        f"Успешных       : "
        f"{state['successful_requests']}"
    )

    print(
        f"Ошибок         : "
        f"{state['failed_requests']}"
    )

    print(
        f"Free-моделей   : "
        f"{len(state['models'])}"
    )

    print("=" * 64)


def handle_status_command():
    """Обработчик команды «статус»/«status». Выводит состояние Brain."""
    show_status()


def handle_show_memory_command():
    """Обработчик команды «память». Краткий список записей."""
    print()
    print(show_memory())


def handle_show_all_memory_command():
    """Обработчик команды «память показать». Полный список записей."""
    print()
    print(show_all_memory())


def handle_memory_status_command():
    """Обработчик команды «память статус». Статистика памяти по категориям."""
    st = status_memory()

    print()
    print(f"Всего записей: {st['total']}")
    print("По категориям:")

    for cat, cnt in st["categories"].items():
        print(f"  {cat}: {cnt}")


def handle_find_memory_command(command):
    """Обработчик команды «память найти <query>». Поиск по памяти."""
    query = command[len("память найти "):].strip()
    print()
    print(find_memory(query))


def handle_clear_memory_command(command):
    """Обработчик команды «память очистить» / «память очистить подтвердить»."""
    confirm = "подтвердить" in command
    print()
    print(clear_memory(confirm=confirm))

def handle_delete_memory_command(question, last_memory_entry_id=None):
    """
    Обработчик пользовательской команды удаления одной записи памяти.
    Безопасный: удаляет только при ровно одном однозначном совпадении
    и только после явного подтверждения «да».
    """
    import re
    q = question.strip()
    lowered = q.lower()
    prefixes = (
        "очисти из памяти ",
        "удали из памяти ",
        "забудь из памяти ",
        "забудь ",
        "удали ",
    )
    query = None
    for p in prefixes:
        if lowered.startswith(p):
            query = q[len(p):].strip()
            break
    if query is None:
        print("\n⚠ Не понял команду удаления. Скажи: «удали из памяти ...».")
        return
    if len(query) < 3:
        print("\n⚠ Слишком расплывчатый запрос. Уточни, какую запись удалить.")
        return

    data = _load_raw()
    entries = data.get("entries", [])
    if not entries:
        print("\n📭 Память пуста.")
        return

    # --- Ссылочные фразы («эту запись», «это», «его», «её» и т.п.) ---
    lowered_q = q.lower()
    ref_phrases = (
        "эту запись", "эта запись", "это число", "это слово",
        "это", "его", "её", "ее",
    )
    is_ref = False
    for _rp in ref_phrases:
        if lowered_q == _rp or lowered_q.endswith(" " + _rp) or lowered_q.endswith(_rp + " запись"):
            is_ref = True
            break
    if is_ref:
        if not last_memory_entry_id:
            print("\n⚠ Не удалось однозначно связать «эту запись». Уточни, какую именно запись удалить.")
            return
        ref_matches = [e for e in entries if e.get("id") == last_memory_entry_id]
        if not ref_matches:
            print("\n⚠ Запись по сохранённому id уже отсутствует. Ничего не удалено.")
            return
        _tgt = ref_matches[0]
        _tid = _tgt.get("id")
        _ttxt = _tgt.get("text", "")
        if not _tid or not isinstance(_tid, str) or len(_tid) < 32:
            print("\n⚠ Внутренняя ошибка: некорректный id. Ничего не удалено.")
            return
        print(f"\nНайдена запись: «{_ttxt}» (id={_tid[:8]})")
        try:
            ans = input("Удалить? (да/нет): ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\nОтменено.")
            return
        if ans not in ("да", "yes", "y", "д"):
            print("Отменено.")
            return
        result = delete_memory(_tid)
        print(f"🗑 {result}")
        return

    uuid_re = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

    # Явный полный id
    if uuid_re.match(query):
        matches = [e for e in entries if e.get("id") == query]
    else:
        words = [w for w in re.findall(r"[а-яa-z0-9]+", query.lower()) if len(w) >= 3]
        if not words:
            print("\n⚠ Слишком расплывчатый запрос. Уточни, какую запись удалить.")
            return
        matches = []
        for e in entries:
            text = str(e.get("text", "")).lower()
            if all(w in text for w in words):
                matches.append(e)

    if not matches:
        print(f"\n⚠ Запись по запросу «{query}» не найдена. Ничего не удалено.")
        return

    if len(matches) > 1:
        print(f"\n⚠ Найдено несколько записей ({len(matches)}). Уточни запрос или укажи полный id:")
        for e in matches[:10]:
            print(f"  [{e.get('id', '')[:8]}] {e.get('text', '')}")
        if len(matches) > 10:
            print(f"  ... и ещё {len(matches) - 10}")
        print("Ничего не удалено.")
        return

    target = matches[0]
    full_id = target.get("id")
    text = target.get("text", "")
    if not full_id or not isinstance(full_id, str) or len(full_id) < 32:
        print("\n⚠ Внутренняя ошибка: некорректный id записи. Ничего не удалено.")
        return

    print(f"\nНайдена запись: «{text}» (id={full_id[:8]})")
    try:
        ans = input("Удалить? (да/нет): ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print("\nОтменено.")
        return
    if ans not in ("да", "yes", "y", "д"):
        print("Отменено.")
        return

    result = delete_memory(full_id)
    print(f"🗑 {result}")


def handle_clear_candidates_command():
    """Очищает очередь кандидатов, не скрывая ошибку записи."""
    if clear_candidates():
        print("\n🧹 Очередь кандидатов очищена.")
    else:
        print("\n⚠ Не удалось очистить очередь. Файл не считается очищенным.")


def handle_memory_candidates_command():
    """Показывает очередь; повреждённая очередь не маскируется под пустую."""
    try:
        candidates = load_candidates()
    except CandidateQueueError as exc:
        print(f"\n⚠ Ошибка чтения очереди кандидатов: {exc}")
        return

    if not candidates:
        print("\n🧠 Очередь кандидатов пуста.")
    else:
        print(f"\n🧠 Кандидатов в очереди: {len(candidates)}")
        for c in candidates:
            print(f"  [{c['id']}] {c['text']}")


def handle_confirm_candidate_command(question):
    """Сохраняет факт в основную память до удаления кандидата из очереди."""
    arg = question[len("память подтвердить"):].strip()
    if not arg:
        print("\n⚠ Укажи id кандидата или 'все'.")
        return

    try:
        candidates = load_candidates()
    except CandidateQueueError as exc:
        print(f"\n⚠ Очередь кандидатов повреждена; подтверждение отменено: {exc}")
        return

    if not candidates:
        print("\n🧠 Очередь кандидатов пуста.")
        return

    if arg != "все":
        resolved_id, resolve_error = resolve_candidate_id(arg, candidates)
        if resolve_error == "CANDIDATE_ID_AMBIGUOUS":
            print("\n⚠ Короткий ID неоднозначен. Укажи полный ID кандидата.")
            return
        if resolve_error:
            print("\n⚠ Кандидат с таким ID не найден.")
            return
        arg = resolved_id

    def persist_candidate(candidate):
        try:
            if candidate.get("target_entry_id"):
                result = update_memory_entry(
                    candidate["target_entry_id"],
                    candidate,
                    expected_text=candidate.get("expected_old_text"),
                )
                if not isinstance(result, str) or not result.startswith("Обновлена запись"):
                    print(f"\n⚠ Уточнение не применено; кандидат оставлен в очереди. Результат: {result}")
                    return False
            else:
                result = add_memory(
                    text=candidate["text"],
                    category=candidate.get("category"),
                    source=candidate.get("source", "brain"),
                    confidence=candidate.get("confidence", 1.0),
                )
        except Exception as exc:
            print(f"\n⚠ Не удалось сохранить факт в основную память: {exc}")
            return False

        if not isinstance(result, str) or result.startswith("MEMORY_") or result.startswith("Пустой текст"):
            print(f"\n⚠ Факт не сохранён; кандидат оставлен в очереди. Результат: {result}")
            return False

        print(f"🧠 Память: {result}")
        return True

    if arg == "все":
        confirmed = 0
        failed = 0
        for candidate in candidates:
            try:
                result = approve_candidate(candidate["id"], persist_candidate)
            except CandidateQueueError as exc:
                failed += 1
                print(f"\n⚠ Ошибка очереди; дальнейшее подтверждение остановлено: {exc}")
                break
            if result:
                confirmed += 1
            else:
                failed += 1
        print(f"\n✅ Подтверждено: {confirmed}; не подтверждено: {failed}.")
        return

    try:
        result = approve_candidate(arg, persist_candidate)
    except CandidateQueueError as exc:
        print(f"\n⚠ Ошибка очереди; кандидат не удалён: {exc}")
        return

    if result:
        print(f"\n✅ Подтверждено: «{result['text']}»")
    else:
        print(f"\n⚠ Кандидат '{arg}' не найден или не сохранён. Если сохранение не удалось, кандидат оставлен в очереди.")


def show_statistics():

    print()

    print("=" * 64)

    print(
        "                    РЕЙТИНГ МОДЕЛЕЙ"
    )

    print("=" * 64)

    if not state["model_stats"]:

        print(
            "Статистика пока отсутствует."
        )

        print("=" * 64)

        return

    ranked = []

    for model_id, stats in (
        state["model_stats"].items()
    ):

        success = stats["success"]

        fail = stats["fail"]

        total = success + fail

        if total:

            reliability = (
                success
                / total
                * 100
            )

        else:

            reliability = 0

        if success:

            avg_time = (
                stats["total_time"]
                / success
            )

        else:

            avg_time = 0

        ranked.append(
            (
                reliability,
                success,
                model_id,
                avg_time
            )
        )

    ranked.sort(
        reverse=True
    )

    for (
        reliability,
        success,
        model_id,
        avg_time
    ) in ranked:

        stats = state["model_stats"].get(
            model_id,
            {}
        )

        print(
            f"{model_id}"
        )

        print(
            f"  Успешных: {success}"
        )

        print(
            f"  Надёжность: "
            f"{reliability:.1f}%"
        )

        rate_429 = stats.get(
            "rate_429",
            0
        )

        cooldown_until = stats.get(
            "cooldown_until",
            0
        )

        if cooldown_until > time.time():

            remaining = max(
                0,
                int(
                    cooldown_until
                    - time.time()
                )
            )

            status_text = (
                f"🟡 cooldown {remaining} сек."
            )

        else:

            status_text = "🟢 доступна"

        print(
            f"  429: {rate_429}"
        )

        print(
            f"  Статус: {status_text}"
        )

        print(
            f"  Среднее время: "
            f"{avg_time:.2f} сек."
        )

        print()


# ============================================================
# [15] ГЛАВНЫЙ ЦИКЛ
# ============================================================

# --------------------------------------------------------
# УПРАВЛЕНИЕ ЛОКАЛЬНЫМИ СЕРВЕРАМИ (запуск/остановка)
# --------------------------------------------------------

LOCAL_SERVER_PROCESSES = {}

LOCAL_SERVER_CONFIGS = {
    "qwen25_3b": {
        "port": 8088,
        "model": "/storage/emulated/0/модели/Qwen2.5-3B-Instruct.Q4_K_M.gguf",
        "ctx_size": 8192,
        "threads": 8,
    },
    "qwen3": {
        "port": 8085,
        "model": "/storage/emulated/0/модели/Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
        "ctx_size": 4096,
        "threads": 8,
    },
}


def cleanup_llama_servers(keep_port=None):
    """Убивает зависшие/лишние llama-server. Чистый Python, без bash."""
    import signal
    killed = 0
    try:
        result = subprocess.run(
            ["ps", "aux"], capture_output=True, text=True, timeout=5
        )
        lines = [l for l in result.stdout.splitlines() if "llama-server" in l and "grep" not in l]
    except Exception:
        return 0

    port_pids = {}
    for line in lines:
        parts = line.split()
        if len(parts) < 8:
            continue
        pid_str, stat, rss_str = parts[1], parts[7], parts[5]
        # Извлекаем порт из аргументов
        port = None
        for i, p in enumerate(parts):
            if p == "--port" and i + 1 < len(parts):
                port = parts[i + 1]
                break

        try:
            pid = int(pid_str)
            rss = int(rss_str)
        except ValueError:
            continue

        # Убиваем zombie и мёртвые (RSS=0)
        if "Z" in stat or rss == 0:
            try:
                os.kill(pid, signal.SIGKILL)
                killed += 1
            except ProcessLookupError:
                pass
            continue

        # Если указан keep_port — убиваем все остальные
        if keep_port is not None and port != str(keep_port):
            try:
                os.kill(pid, signal.SIGKILL)
                killed += 1
            except ProcessLookupError:
                pass
            continue

        # Дубликаты на одном порту — оставляем последний
        if port:
            if port in port_pids:
                old_pid = port_pids[port]
                try:
                    os.kill(old_pid, signal.SIGKILL)
                    killed += 1
                except ProcessLookupError:
                    pass
            port_pids[port] = pid

    if killed > 0:
        time.sleep(1)
    return killed


def _stop_local_llama_by_config(name):
    """
    Находит и убивает llama-server, соответствующий LOCAL_SERVER_CONFIGS[name].
    Критерий: бинарь + --model + --port (через /proc/<pid>/cmdline).
    Возвращает число убитых.
    """
    import signal as _signal
    config = LOCAL_SERVER_CONFIGS.get(name)
    if not config:
        return 0
    llama_bin = os.path.expanduser("~/llama.cpp/build/bin/llama-server")
    want_model = config.get("model")
    want_port = str(config.get("port"))
    killed = 0
    try:
        result = subprocess.run(["ps", "-ef"], capture_output=True, text=True, timeout=5)
        lines = result.stdout.splitlines()
    except Exception:
        return 0
    for line in lines:
        if "llama-server" not in line or "grep" in line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            pid = int(parts[1])
        except ValueError:
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                raw = f.read().split(b"\x00")
            args = [a.decode("utf-8", errors="replace") for a in raw if a]
        except Exception:
            continue
        if not args or args[0] != llama_bin:
            continue
        model_ok = False
        port_ok = False
        for i, a in enumerate(args):
            if a == "--model" and i + 1 < len(args):
                if args[i + 1] == want_model:
                    model_ok = True
            if a == "--port" and i + 1 < len(args):
                if args[i + 1] == want_port:
                    port_ok = True
        if model_ok and port_ok:
            try:
                os.kill(pid, _signal.SIGKILL)
                killed += 1
            except ProcessLookupError:
                pass
    return killed


def start_local_server(name):
    """Запускает llama-server для указанной локальной модели."""
    import subprocess

    # Автокоррекция опечаток
    corrected_name, was_corrected = autocorrect_local_model(name)
    if was_corrected:
        print(f"  ✏️  Автокоррекция: '{name}' → '{corrected_name}'")
        name = corrected_name

    # Очистка зависших серверов перед запуском
    config = LOCAL_SERVER_CONFIGS.get(name, {})
    keep_port = config.get("port")
    cleaned = cleanup_llama_servers(keep_port=keep_port)
    if cleaned > 0:
        print(f"  🧹 Очищено зависших серверов: {cleaned}")

    if name in LOCAL_SERVER_PROCESSES:
        proc = LOCAL_SERVER_PROCESSES[name]
        if proc.poll() is None:
            return True

    config = LOCAL_SERVER_CONFIGS.get(name)
    if not config:
        return False

    service = LOCAL_MODEL_SERVICES.get(name)
    if not service:
        return False

    # P0.5: не переиспользуем неконтролируемый существующий сервер.
    # Останавливаем фантом LOCAL (по бинарю + модели + порту),
    # затем всегда поднимаем свой через subprocess.Popen.
    _phantoms = _stop_local_llama_by_config(name)
    if _phantoms > 0:
        print(f"  🧹 Остановлено фантомов LOCAL: {_phantoms}")
        time.sleep(1)

    llama_bin = os.path.expanduser("~/llama.cpp/build/bin/llama-server")
    if not os.path.exists(llama_bin):
        print(f"  ❌ llama-server не найден: {llama_bin}")
        return False

    cmd = [
        llama_bin,
        "--model", config["model"],
        "--host", "127.0.0.1",
        "--port", str(config["port"]),
        "--ctx-size", str(config["ctx_size"]),
        "--threads", str(config["threads"]),
        "--parallel", "1",
        "--flash-attn", "on",
        # CPU-only: Vulkan 0.4.1 на Adreno 735 ломается на квант. matmul
        # (ErrorUnknown/segfault, эксперимент 2026-09-15); без флага — hang/500
        "--n-gpu-layers", "0",
    ]

    try:
        # Audit #12a' LLAMA_STABILITY: log vmesto /dev/null - predsmertnye
        # zapisi servera vidny; povedenie (privyazka k sessii, avtoklin,
        # stop) NE izmeneno - reshenie vladeltsa.
        log_file = open(os.path.expanduser("~/llama.cpp/server.log"), "a", encoding="utf-8")
        proc = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            close_fds=True,
        )
        LOCAL_SERVER_PROCESSES[name] = proc
        print(f"  🚀 {name}: запущен (PID {proc.pid})")

        for _ in range(90):
            time.sleep(1)
            if check_local_health(service, timeout=1):
                return True

        print(f"  ⚠ {name}: не ответил за 90 сек")
        return False

    except Exception as e:
        print(f"  ❌ {name}: ошибка запуска: {e}")
        return False


def stop_local_server(name=None):
    """Останавливает llama-server. Если name=None — останавливает все."""
    names = [name] if name else list(LOCAL_SERVER_PROCESSES.keys())

    for n in names:
        proc = LOCAL_SERVER_PROCESSES.get(n)
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
            print(f"  🛑 {n}: остановлен")
            del LOCAL_SERVER_PROCESSES[n]



def handle_write_command(question):
    raw = question[6:]
    if "|" not in raw:
        print("\n⚠ Формат: write <путь> | <текст>")
        return
    file_path, file_content = raw.split("|", 1)
    file_path = file_path.strip()
    file_content = file_content.strip()
    tool_result = tool_execute("write_file", {"path": file_path, "content": file_content})
    if tool_result["ok"]:
        print(f"\n✅ {tool_result['result']}")
    else:
        print(f"\n⚠ Ошибка: {tool_result['error']}")


def handle_read_command(question):
    file_path = question[5:].strip()
    if file_path.lower().endswith(".pdf"):
        tool_result = tool_execute("read_pdf", {"path": file_path})
    elif file_path.lower().endswith(".docx"):
        tool_result = tool_execute("read_docx", {"path": file_path})
    else:
        tool_result = tool_execute("read_file", {"path": file_path})
    if tool_result["ok"]:
        print(f"\n✅ Содержимое:\n{tool_result['result']}")
    else:
        print(f"\n⚠ Ошибка: {tool_result['error']}")


def handle_statistics_command():
    show_statistics()


def handle_run_command(question):
    shell_cmd = question[4:].strip()
    tool_result = tool_execute("shell", {"command": shell_cmd})
    if tool_result["ok"]:
        print(f"\n✅ Результат:\n{tool_result['result']}")
    else:
        print(f"\n⚠ Ошибка: {tool_result['error']}")
        if "COMMAND_NOT_ALLOWED" in (tool_result["error"] or ""):
            print("\n🤖 Уточняю у модели...")
            hint = get_command_hint(shell_cmd, TOOL_ALLOWED_COMMANDS)
            if hint:
                print(f"\n💡 Подсказка: {hint}")


def handle_remember_command(question):
    candidate = detect_fact_candidate(question)
    if not candidate:
        print("⚠️ После «запомни» нужно указать, что сохранить.")
        return
    result = add_memory(
        text=candidate["text"],
        category=candidate.get("category"),
        source=candidate.get("source", "user_explicit"),
        confidence=candidate.get("confidence", 1.0),
    )
    print(f"🧠 Память: {result}")


def handle_models_command(messages):
    models_text = show_models()
    if models_text:
        messages.append({
            "role": "assistant",
            "content": models_text
        })
        # UI-ветка: слой модели не определён -> без суммаризации (LOCAL-фича)
        trim_history(messages, allow_summary=False)


def handle_clear_command(messages):
    messages.clear()
    print(
        "\nИстория очищена."
    )


def handle_reset_command(state):
    state[
        "model_stats"
    ].clear()

    state[
        "last_glm_failure"
    ] = 0

    save_stats()

    print(
        "\nСтатистика сброшена."
    )


def handle_exit_command():
    save_stats()

    stop_local_server()
    print(
        "\nДо встречи."
    )



def run_brain_multistep_execution(goal=None, task_id=None):
    """Run one persisted Planner task through bounded Tool Bridge execution."""
    print("\n" + "=" * 64)
    print("BRAIN 1.4 — МНОГОШАГОВОЕ ИСПОЛНЕНИЕ")
    print("=" * 64)

    route = None
    if state.get("model_lock_type") == "MANUAL":
        if state.get("model_lock_layer") in ("API", "GEMINI"):
            route = {
                "model": state.get("model_lock"),
                "layer": state.get("model_lock_layer"),
                "lock_type": "MANUAL",
            }
        else:
            print("⚠ Выбрана LOCAL-модель без поддержки Tool Bridge. Переключи модель на API или Gemini.")
            return None
    else:
        candidates = rank_models("reasoning")
        if candidates:
            _model_id = candidates[0].get("id")
            if _model_id:
                route = {
                    "model": _model_id,
                    "layer": "GEMINI" if _model_id in GEMINI_MODELS else "API",
                    "lock_type": "EXECUTION",
                }
    if not route:
        print("⚠ Нет доступной API-модели для исполнения инструментальных шагов.")
        return None

    if task_id:
        try:
            task_record = task_manager.get_task(task_id)
        except task_manager.TaskManagerError as error:
            print(f"⚠ Задача не найдена: {error}")
            return None
        goal = task_record.get("title", "")
        plan = task_record.get("plan")
        if not isinstance(plan, dict):
            print("⚠ У задачи нет сохранённого плана. Исполнение остановлено.")
            return None
        if task_record.get("status") == "completed":
            print("ℹ Задача уже завершена.")
            return None
        if task_record.get("status") != "active":
            try:
                task_record = task_manager.start_task(task_id)
            except task_manager.TaskManagerError as error:
                print(f"⚠ Не удалось возобновить задачу: {error}")
                return None
    else:
        if not isinstance(goal, str) or not goal.strip():
            print("⚠ Укажи цель: исполнить <описание задачи>")
            return None
        plan_only = execution_intent.is_plan_only_request(goal)
        analysis_messages = [
            {
                "role": "system",
                "content": (
                    "Ты — аналитик Personal AI Brain. Проанализируй цель, ограничения, "
                    "неизвестные условия, риски и какие наблюдаемые результаты нужно получить. "
                    "Не выполняй действия, не вызывай инструменты и не утверждай, что задача выполнена. "
                    "Ответь кратко и структурированно на русском."
                ),
            },
            {"role": "user", "content": f"Проанализируй цель перед планированием:\n{goal.strip()}"},
        ]
        analysis_ok, analysis_result = controller_execute(route, analysis_messages, tools=None)
        if not analysis_ok:
            print(f"⚠ Анализ не выполнен: {_format_execution_model_error(analysis_result)}")
            return None
        analysis_text = str(analysis_result.get("answer", "")).strip()
        if not analysis_text:
            print("⚠ Анализ вернул пустой результат. Исполнение остановлено.")
            return None
        print("\nАНАЛИЗ ЦЕЛИ")
        print(analysis_text[:3000])

        plan_messages = [
            {"role": "system", "content": planner.PLAN_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Построй проверяемый DAG-план для исполнения цели. "
                    f"Не заявляй, что шаги уже выполнены.\n"
                    f"Цель: {goal.strip()}\n\nАнализ:\n{analysis_text[:6000]}"
                ),
            },
        ]
        plan_ok, plan_result = controller_execute(route, plan_messages, tools=None)
        if not plan_ok:
            print(f"⚠ Не удалось построить план: {_format_execution_model_error(plan_result)}")
            return None
        try:
            plan = planner.parse_plan_response(plan_result.get("answer", ""), goal)
            task_record = task_manager.create_task(
                goal.strip(),
                details="Анализ Brain 1.4:\n" + analysis_text[:6000],
                plan=plan,
            )
            task_id = task_record["id"]
            if plan_only:
                print("\nРЕЖИМ: ТОЛЬКО ПЛАН — исполнение шагов не запускалось.")
                print("\n" + planner.format_plan(plan))
                print(
                    f"\n💾 План сохранён как ожидающая задача {task_id}. "
                    f"Для явного запуска: исполнить задача {task_id}"
                )
                return {
                    "status": "planned",
                    "task_id": task_id,
                    "plan": plan,
                }
            task_record = task_manager.start_task(task_id)
        except (planner.PlanValidationError, task_manager.TaskManagerError) as error:
            print(f"⚠ План не сохранён или не прошёл проверку: {error}")
            return None


    # После аварийного прерывания in_progress нельзя повторять автоматически:
    # пользователь должен определить, был ли внешний эффект уже применён.
    for interrupted_step in [
        item for item in plan.get("steps", [])
        if item.get("status") == "in_progress"
    ]:
        print(
            f"\n⚠ Шаг {interrupted_step.get('id')} был начат, но его итог не зафиксирован."
            "\nПовтор может дублировать внешний эффект."
        )
        try:
            decision = input("Введи 'готово' с доказательством, 'повторить' если шаг точно не выполнен, или Enter для остановки: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            decision = ""
        if decision == "готово":
            evidence = {}
            for criterion in interrupted_step.get("acceptance_criteria", []):
                try:
                    proof = input(
                        f"Доказательство {criterion.get('id')} ({criterion.get('description')}): "
                    ).strip()
                except (KeyboardInterrupt, EOFError):
                    proof = ""
                if not proof:
                    print("⚠ Без доказательства шаг не будет отмечен завершённым.")
                    interrupt_current_task()
                    return None
                evidence[criterion["id"]] = {
                    "passed": True,
                    "evidence": "Ручная сверка после прерывания: " + proof,
                }
            try:
                planner.complete_step(plan, interrupted_step["id"], evidence)
            except planner.PlanValidationError as error:
                print(f"⚠ Не удалось подтвердить шаг: {error}")
                interrupt_current_task()
                return None
        elif decision == "повторить":
            try:
                confirm_repeat = input(
                    "Подтверди, что действие не было выполнено или безопасно повторяемо [да/нет]: "
                ).strip().lower()
            except (KeyboardInterrupt, EOFError):
                confirm_repeat = ""
            if confirm_repeat != "да":
                print("Исполнение остановлено; шаг не повторялся.")
                interrupt_current_task()
                return None
            interrupted_step["status"] = "pending"
            interrupted_step["evidence"] = {}
            plan["status"] = (
                "in_progress"
                if any(item.get("status") == "completed" for item in plan.get("steps", []))
                else "pending"
            )
        else:
            print("Исполнение остановлено без повторного запуска шага.")
            interrupt_current_task()
            return None
        try:
            task_manager.update_progress(
                task_id,
                note=f"Ручная сверка шага {interrupted_step.get('id')}",
                plan=plan,
                checkpoint={
                    "phase": "manual_reconciliation",
                    "step_id": interrupted_step.get("id"),
                    "decision": decision,
                },
            )
        except task_manager.TaskManagerError as error:
            print(f"⚠ Не удалось сохранить ручную сверку: {error}")
            interrupt_current_task()
            return None

    def interrupt_current_task():
        try:
            current = task_manager.get_task(task_id)
            if current.get("status") == "active":
                task_manager.interrupt_task(task_id)
        except task_manager.TaskManagerError:
            pass

    allowed_tool_names = {
        item.get("function", {}).get("name")
        for item in get_tool_definitions()
        if item.get("function", {}).get("name")
    }

    def approve_tool(tool_name, params):
        return _authorize_model_tool_call(tool_name, params)

    def execute_step(step):
        step_results = {}
        step_messages = [
            {
                "role": "system",
                "content": (
                    "Ты — исполнитель одного шага Personal AI Brain. "
                    "Выполни только указанный шаг с помощью доступных инструментов. "
                    "Не выполняй соседние шаги и не выдумывай результаты. "
                    "Для каждого действия используй инструмент; после результата "
                    "кратко сообщи, что реально сделано и что осталось. "
                    "Если инструмент не нужен, объясни почему. "
                    "Любой инструмент, кроме безопасного чтения, потребует подтверждения пользователя."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Общая цель: {goal}\n"
                    f"Шаг: {step.get('id')} — {step.get('title')}\n"
                    f"Описание: {step.get('description')}\n"
                    f"Критерии:\n" + "\n".join(
                        f"- {item.get('id')}: {item.get('description')}"
                        for item in step.get("acceptance_criteria", [])
                    )
                ),
            },
        ]
        ok, result = run_with_tools(
            route,
            step_messages,
            _executed_calls=set(),
            _denied_tools=set(),
            _tool_results=step_results,
            allowed_tool_names=allowed_tool_names,
            before_tool_call=approve_tool,
        )
        normalized = []
        for (name, raw_args), tool_result in step_results.items():
            try:
                params = json.loads(raw_args) if isinstance(raw_args, str) else {}
            except Exception:
                params = {}
            normalized.append({
                "tool_name": name,
                "params": params if isinstance(params, dict) else {},
                "result": tool_result,
            })
        return {
            "ok": ok,
            "answer": result.get("answer", "") if isinstance(result, dict) else "",
            "error": result.get("error") if isinstance(result, dict) else "INVALID_MODEL_RESULT",
            "tool_results": normalized,
        }

    def verify_step(step, outcome):
        tool_results = outcome.get("tool_results", [])
        for item in tool_results:
            result = item.get("result") or {}
            if result.get("ok") is not True:
                return {"status": "FAIL", "reason": str(result.get("error") or "TOOL_FAILED")}
            goal_check = result.get("goal_verification") or {}
            if goal_check.get("status") == "FAIL":
                return {
                    "status": "FAIL",
                    "reason": ", ".join(goal_check.get("reasons", [])) or "GOAL_VERIFICATION_FAILED",
                }

        criteria = step.get("acceptance_criteria", [])
        evidence = {}
        if len(criteria) == 1 and len(tool_results) == 1:
            goal_check = (tool_results[0].get("result") or {}).get("goal_verification") or {}
            if goal_check.get("status") == "PASS":
                evidence[criteria[0]["id"]] = {
                    "passed": True,
                    "evidence": (
                        f"Goal Verifier PASS; tool={tool_results[0].get('tool_name')}; "
                        + ", ".join(goal_check.get("reasons", []))
                    ),
                }
                return {"status": "PASS", "evidence": evidence}

        print(f"\nПроверка шага {step.get('id')}: автоматических доказательств недостаточно.")
        for criterion in criteria:
            print(f"Критерий: {criterion.get('id')} — {criterion.get('description')}")
            try:
                proof = input("Введи наблюдаемое подтверждение (пусто — остановить): ").strip()
            except (KeyboardInterrupt, EOFError):
                proof = ""
            if not proof:
                return {"status": "UNCERTAIN", "reason": "HUMAN_VERIFICATION_REQUIRED"}
            evidence[criterion["id"]] = {
                "passed": True,
                "evidence": "Подтверждение пользователя: " + proof,
            }
        return {"status": "PASS", "evidence": evidence}

    def persist(event, current_plan, step, detail):
        step_id = step.get("id") if isinstance(step, dict) else None
        checkpoint = {
            "phase": event,
            "step_id": step_id,
            "completed_steps": [
                item["id"] for item in current_plan.get("steps", [])
                if item.get("status") == "completed"
            ],
            "detail": detail,
        }
        task_manager.update_progress(
            task_id,
            note=f"{event}: {step_id or 'all'}",
            plan=current_plan,
            checkpoint=checkpoint,
        )

    report = execution_engine.run_multistep(
        goal,
        plan,
        execute_step,
        verify_step,
        persist=persist,
        max_safe_retries=1,
    )

    if report.get("status") == "completed":
        try:
            task_manager.complete_task(task_id)
        except task_manager.TaskManagerError as error:
            report["status"] = "paused"
            report["reason"] = "TASK_COMPLETION_PERSISTENCE_FAILED"
            print(f"⚠ План выполнен, но статус задачи не сохранён: {error}")
    else:
        try:
            current_task = task_manager.get_task(task_id)
            if current_task.get("status") == "active":
                task_manager.interrupt_task(task_id)
        except task_manager.TaskManagerError:
            pass

    print("\n" + execution_engine.format_report(report))
    print(f"ID задачи: {task_id}")
    return report


def main():
    # Безопасная проверка обновлений до запуска сервисов и загрузки пользовательских данных.
    try:
        import brain_auto_update
        _update_result = brain_auto_update.apply_update_if_safe()
    except Exception as _update_error:
        # Сбой обновления не должен блокировать запуск основной системы.
        print(f"⚠️ Проверка обновлений пропущена: {_update_error}")
        _update_result = {}

    if _update_result.get("status") == "updated":
        print(
            "\n⬆️ Brain обновлён: "
            f"{_update_result.get('from', '')[:8]} → "
            f"{_update_result.get('to', '')[:8]}"
        )
        print(f"Резервная копия Git: {_update_result.get('backup')}")
        print("Перезапуск Brain для загрузки новой версии...")
        os.execv(
            sys.executable,
            [sys.executable, os.path.abspath(__file__), *sys.argv[1:]],
        )
    elif _update_result.get("status") == "skipped":
        _reason = _update_result.get("reason")
        if _reason not in ("not_fast_forward",):
            print(f"ℹ️ Автообновление не применено: {_reason}")

    # Авто-остановка серверов при выходе
    import atexit
    import signal

    def _shutdown(signum=None, frame=None):
        mcp_bridge.mcp_stop()
        stop_local_server()
        # Убиваем ВСЕ оставшиеся llama-server (включая те, что не в dict)
        cleanup_llama_servers()
        if signum is not None:
            sys.exit(0)

    atexit.register(_shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # Запуск MCP filesystem server
    mcp_bridge.mcp_start()


    # Инициализация долговременной памяти
    try:
        memory_data = load_memory()
        print(f"🧠 Память загружена: {len(memory_data.get('entries', []))} записей")
    except Exception as e:
        print(f"⚠️ Ошибка загрузки памяти: {e}")

    # Хранилище предложений использует существующую директорию AI_Brain.
    global TOOL_PROPOSAL_MANAGER
    try:
        _proposal_store = os.path.join(os.path.dirname(MEMORY_FILE), "tool_proposals.json")
        TOOL_PROPOSAL_MANAGER = phase4_proposal_manager.ToolProposalManager(
            _proposal_store, REGISTRY
        )
    except Exception as _proposal_error:
        TOOL_PROPOSAL_MANAGER = None
        print(f"⚠️ Хранилище предложений недоступно: {_proposal_error}")

    load_stats()

    try:
        _recovered_tasks = task_manager.recover_active_tasks()
        if _recovered_tasks:
            print(f"♻️ Восстановлено прерванных задач: {len(_recovered_tasks)}")
    except task_manager.TaskManagerError as _task_error:
        print(f"⚠️ Хранилище задач недоступно: {_task_error}")

    print()

    print("=" * 64)
    print("🧠 PERSONAL AI BRAIN")
    print("   Demo v1.0")
    print("=" * 64)

    print()

    print("Персональный AI-ассистент")
    print("Автовыбор модели · Память · Инструменты · Многострочный ввод: long")

    print()

    print("🟢 Brain готов к работе")

    print()

    print("Команды:")
    print("  статус      — состояние")
    print("  план <задача> — построить и сохранить план")
    print("  исполнить <цель> — выполнить многошаговый план")
    print("  исполнить задача <ID> — продолжить сохранённую задачу")
    print("  задачи      — список задач")
    print("  задача создать <название> — создать задачу")
    print("  задача <ID> — подробности задачи")
    print("  задача продолжить <ID> — восстановить работу")
    print("  задача прогресс <ID> <текст> — сохранить точку продолжения")
    print("  задача шаг начать <ID> <ШАГ> / задача шаг завершить <ID> <ШАГ> <JSON>")
    print("  задача прервать <ID> / задача завершить <ID>")
    print("  модели      — Free-модели")
    print("  рейтинг     — рейтинг моделей")
    print("  очистить    — очистить историю")
    print("  model auto  — вернуть автоподбор модели")
    print("  local stop  — остановить локальные серверы")
    print("  сброс       — сбросить статистику")
    print("  чаты        — список чатов")
    print("  чат N       — открыть чат по номеру")
    print("  новый чат [Название] — создать чат")
    print("  чат название Новое имя — переименовать активный чат")
    print("  контекст [домен] — показать или изменить контекст чата")
    print("  предложения — список предложений инструментов")
    print("  предложение <ID> — подробности предложения")
    print("  предложение одобрить <ID> / отклонить <ID> — решение после подтверждения")
    print("  выход       — завершить работу")

    print("=" * 64)

    _active_chat = chat_system.load_or_create_active_chat()
    _active_chat_id = _active_chat.get("id") if _active_chat else None
    _active_chat_title = (_active_chat.get("title") if _active_chat else None) or "Новый чат"
    _active_chat_created_at = _active_chat.get("created_at") if _active_chat else None
    _active_chat_domain = (_active_chat.get("context_domain") if _active_chat else None) or "general"

    messages = []

    messages.append({
        "role": "system",
        "content": (
            "Ты — Personal AI Brain, персональный AI-ассистент пользователя. "
            "Всегда отвечай на русском языке, если пользователь не просит иначе. "
            "Давай короткие, конкретные и точные ответы. "
            "Если пишешь код, добавляй комментарии на русском. "
            "Для изменения файлов ВСЕГДА вызывай инструменты file_edit или write_file. "
            "НИКОГДА не выводи изменённый код в текст ответа — изменения применяются только через вызов инструментов."
        )
    })

    # Patch 2.1: восстановить conversation из active chat.
    # system prompt уже добавлен выше; transient сообщения восстановлению не подлежат
    # (по контракту 2.2 они не будут сохранены).
    if _active_chat:
        for _m in (_active_chat.get("messages") or []):
            if _m.get("role") != "system":
                messages.append(_m)

    # --------------------------------------------------------
    # WARMUP — прогрев модели перед началом работы
    # --------------------------------------------------------

    print()
    print("⏳ Прогрев модели...")

    warmup_messages = [
        {"role": "system", "content": "Ты — помощник. Ответь коротко."},
        {"role": "user", "content": "Привет"}
    ]

    warmup_success = False
    last_warmup_error = None
    warmup_route = controller_route("general")

    if not warmup_route:
        print("⏳ Подбираю доступный AI...")
        print("⚠️ Сейчас нет свободного AI. Попробуйте ещё раз через несколько минут.")
    else:
        warmup_model = warmup_route.get("model", PRIMARY_MODEL)

        for warmup_attempt in range(1, 4):
            try:
                ok, warmup_result = ask_warmup_model(
                    warmup_route,
                    warmup_messages,
                )

                if ok:
                    warmup_success = True
                    break

                error = warmup_result.get("error", "")
                last_warmup_error = error
                if error in ("WARMUP_SKIPPED_NON_FREE_MODEL",) or error.startswith(
                    "WARMUP_UNSUPPORTED_LAYER:"
                ):
                    # Детерминированный отказ: повторять запрос не нужно.
                    break
                if error == "429":
                    # Эта модель в лимите, пробуем следующую
                    warmup_route = controller_route("general")
                    if not warmup_route:
                        break
                    warmup_model = warmup_route.get("model", PRIMARY_MODEL)
                    continue

            except Exception:
                pass

            time.sleep(1 + warmup_attempt)

        if warmup_success:
            print(f"✅ Модель готова к работе ({warmup_model.split('/')[-1]})")
        elif last_warmup_error == "WARMUP_SKIPPED_NON_FREE_MODEL":
            print(
                f"⏭ Прогрев пропущен: {warmup_model} не подтверждена как бесплатная; "
                "платный запрос не отправлялся."
            )
        elif last_warmup_error and last_warmup_error != "429":
            warmup_layer = warmup_route.get("layer", "API")
            print(
                f"⚠ Ошибка прогрева [{warmup_layer}:{warmup_model}]: "
                f"{last_warmup_error}"
            )
        else:
            print("⏳ Подбираю доступный AI...")
            print("⚠️ Сейчас нет свободного AI. Попробуйте ещё раз через несколько минут.")

    print()

    last_memory_entry_id = None

    while True:

        try:

            question = input(
                f"\nТы [{_active_chat_title}]: "
            ).strip()

        except (
            KeyboardInterrupt,
            EOFError
        ):

            print(
                "\nВыход."
            )

            break

        if not question:

            continue

        voice_input = False
        command = question.lower()

        # Автоматически объединяем строки/сообщения, поступившие подряд.
        # Команда long сохраняет прежний ручной режим без изменений.
        if not (command == "long" or (command.startswith("long") and len(question) > 4)):
            _text, _cancelled, _was_empty = _collect_burst_input(
                question, reader=input, idle_timeout=2.0
            )
            if _cancelled:
                print("\n⚠ Автоматический ввод отменён.")
                continue
            if not _was_empty:
                question = _text
                command = question.lower()
                if "\n" in question:
                    print(f"\n📝 Автоматически объединено строк: {question.count(chr(10)) + 1}")

        # ----------------------------------------------------
        # [20] LONG — многострочный ввод (защита от bracketed paste)
        # ----------------------------------------------------

        if command == "long" or (command.startswith("long") and len(question) > 4):
            glued_first_line = question[4:] if command != "long" else None
            print("\n📝 Режим многострочного ввода. Вставляй текст, "
                  "в конце введи строку 'конец' на отдельной строке.")
            initial = [glued_first_line] if glued_first_line else None
            # Variant D: temporarily replace SIGINT handler so Ctrl+C
            # in long mode raises KeyboardInterrupt (caught by helper),
            # instead of triggering _shutdown (which exits Brain).
            _old_sigint = signal.getsignal(signal.SIGINT)
            try:
                signal.signal(signal.SIGINT, signal.default_int_handler)
                _text, _cancelled, _was_empty = _collect_multiline_input(
                    reader=input, initial_lines=initial
                )
            finally:
                signal.signal(signal.SIGINT, _old_sigint)
            if _cancelled:
                print("\n⚠ Ввод отменён.")
                continue
            if _was_empty:
                print("\n⚠ Пустой ввод, отменено.")
                continue
            question = _text
            command = question.lower()


        # ----------------------------------------------------
        # ВЫХОД
        # ----------------------------------------------------

        if command in {
            "выход",
            "exit",
            "quit",
            "q"
        }:

            handle_exit_command()

            break

        # P4.3.2: proposal commands are accepted only from direct terminal input.
        if command == "предложения" or command.startswith("предложение "):
            phase4_proposal_commands.handle_proposal_command(
                command, TOOL_PROPOSAL_MANAGER
            )
            continue

        # ----------------------------------------------------
        # MODEL CONTROLLER
        # ----------------------------------------------------

        # ----------------------------------------------------
        # [17] RUN — вызов TOOL CONTROLLER (shell)
        # ----------------------------------------------------

        # ----------------------------------------------------
        # [18] READ — вызов TOOL CONTROLLER (files, read-only)
        # ----------------------------------------------------

        # ----------------------------------------------------
        # [18] WRITE — вызов TOOL CONTROLLER (files, create-only)
        # ----------------------------------------------------

        if command.startswith("write "):
            handle_write_command(question)
            continue

        if command.startswith("read "):
            handle_read_command(question)
            continue

        if command.startswith("run "):
            handle_run_command(question)
            continue

        controller_result = controller_handle_model_command(
            question
        )

        if controller_result is not None:
            # UI: человеческое сообщение вместо технического dict
            _cr_layer = controller_result.get("layer") if isinstance(controller_result, dict) else None
            _cr_model = controller_result.get("model") if isinstance(controller_result, dict) else None
            _cr_lock = controller_result.get("lock_type") if isinstance(controller_result, dict) else None
            _cr_message = controller_result.get("message") if isinstance(controller_result, dict) else None

            _local_display = {
                "qwen3": "Qwen 3 4B",
                "qwen25_3b": "Qwen 2.5 3B",
            }

            if _cr_layer == "LOCAL" and _cr_model:
                _display_name = _local_display.get(_cr_model, _cr_model)
                print(f"📱 {_display_name} активна")
            elif _cr_lock == "AUTO":
                print("🧠 Автовыбор AI активен")
            elif _cr_lock == "MANUAL" and _cr_model:
                _display_name = _local_display.get(_cr_model, _cr_model)
                print(f"🧠 Модель: {_display_name}")
            elif _cr_message:
                print(f"🧠 {_cr_message}")
            elif controller_result is not None:
                print("🧠 Состояние модели обновлено")
            continue

        # ----------------------------------------------------
        # ----------------------------------------------------
        # АВТОМАТИЧЕСКОЕ ЗАПОМИНАНИЕ
        # ----------------------------------------------------

        if command == "запомни" or command.startswith("запомни") or command == "сохрани" or command.startswith("сохрани"):
            handle_remember_command(question)
            continue

        # СТАТУС
        # ----------------------------------------------------

        if command in {
            "статус",
            "status"
        }:

            handle_status_command()

            continue

        # ----------------------------------------------------
        # ПАМЯТЬ — очередь кандидатов (Fact Extraction 2.0)
        # ----------------------------------------------------

        if command in {"память кандидаты", "память очередь"}:
            handle_memory_candidates_command()
            continue

        if command.startswith("память подтвердить"):
            handle_confirm_candidate_command(question)
            continue

        if command in {"память очистить-очередь", "память очистить очередь"}:
            handle_clear_candidates_command()
            continue

        # ----------------------------------------------------
        # МОДЕЛИ
        # ----------------------------------------------------

        # ----------------------------------------------------
        # SELFCHECK
        # ----------------------------------------------------

        # ----------------------------------------------------
        # VOICE — голосовой ввод (STT до модели, затем обычный pipeline)
        # ----------------------------------------------------

        if command in {
            "voice",
            "голос"
        }:

            recognized = voice_cmd()

            if not recognized:
                continue

            print(f"\n🎤 Распознано: {recognized}\n")
            # Подменяем вопрос: command остаётся "voice", другие ветки не
            # совпадут, поток доходит до detect_task -> route -> run_with_tools
            question = recognized
            voice_input = True

        # ----------------------------------------------------
        # BRIEF — брифинг из памяти (без модели, read-only)
        # ----------------------------------------------------

        if command in {
            "brief",
            "брифинг"
        }:

            brief_cmd()

            # БРИФИНГ-постобработка (Termux:API):
            # батарея + notification поверх вывода brief_cmd
            try:
                import subprocess as _sp, json as _json
                from datetime import datetime as _dt

                entries = _load_raw().get("entries", [])
                recent = sorted(
                    entries,
                    key=lambda e: str(e.get("timestamp", "")),
                    reverse=True
                )[:7]

                try:
                    _r = _sp.run(
                        ["termux-battery-status"],
                        capture_output=True,
                        text=True,
                        timeout=15,
                    )
                    _b = _json.loads(_r.stdout)
                    batt = (
                        f"🔋 {_b.get('percentage', '?')}%, "
                        f"{_b.get('status', '?')}, "
                        f"{_b.get('temperature', '?')}°C"
                    )
                except Exception:
                    batt = "🔋 недоступна"

                lines = [
                    f"БРИФИНГ — {_dt.now().strftime('%d.%m.%Y %H:%M')}",
                    f"Записей в памяти: {len(entries)}",
                    batt,
                ]

                if recent:
                    lines.append("Свежие записи:")
                    for e in recent:
                        _t = " ".join(str(e.get("text", "")).split())
                        lines.append(
                            f"  • [{e.get('category', '?')}|imp {e.get('importance', '?')}] {_t[:110]}"
                        )

                brief = "\n".join(lines)

                _res = tool_execute("notify_user", {
                    "title": "AI Brain — Брифинг",
                    "message": brief[:512],
                })

                if not _res.get("ok"):
                    print(
                        f"  ⚠ Notification не доставлен: "
                        f"{_res.get('error')}"
                    )

            except Exception as e:
                print(f"  ⚠ Notification-блок брифинга не удался: {e}")

            continue

        if command in {
            "selfcheck",
            "диагностика"
        }:

            selfcheck_cmd()

            continue

        if command in {
            "модели",
            "models"
        }:

            handle_models_command(messages)

            continue

        # ----------------------------------------------------
        # РЕЙТИНГ
        # ----------------------------------------------------

        if command in {
            "рейтинг",
            "статистика",
            "stats",
            "statistics"
        }:

            handle_statistics_command()

            continue

        # ----------------------------------------------------
        # ОЧИСТКА
        # ----------------------------------------------------

        if command in {
            "очистить",
            "clear"
        }:

            handle_clear_command(messages)

            continue

        # ----------------------------------------------------
        # ЧАТЫ (UI-слой над chat_system.py)
        # ----------------------------------------------------

        if command == "чаты":
            _chats = chat_system.list_chats()
            if not _chats:
                print("\n📭 Чатов нет. Создай: «новый чат Название»")
                continue
            print()
            print("=" * 64)
            print("СПИСОК ЧАТОВ")
            print("=" * 64)
            for _i, _c in enumerate(_chats, 1):
                _marker = " ◀ активный" if _c.get("id") == _active_chat_id else ""
                print(f"  {_i:2d}. {_c.get('title', 'Новый чат')}{_marker}")
            print("=" * 64)
            print("Открыть: «чат N»  ·  Новый: «новый чат [Название]»")
            continue

        if command == "новый чат" or command.startswith("новый чат "):
            _sys_msg = next((m for m in messages if m.get("role") == "system"), None)
            if _sys_msg is None:
                print("\n⚠ Не найдено system-сообщение. Операция отменена.")
                continue
            _title = question[len("новый чат"):].strip() or None
            _new = chat_system.create_new_chat(title=_title, context_domain=_active_chat_domain)
            if not _new:
                print("\n⚠ Не удалось создать чат.")
                continue
            _active_chat = _new
            _active_chat_id = _new.get("id")
            _active_chat_title = _new.get("title") or "Новый чат"
            _active_chat_created_at = _new.get("created_at")
            _active_chat_domain = _new.get("context_domain", "general")
            messages.clear()
            messages.append(_sys_msg)
            print(f"\n📁 Создан новый чат: {_active_chat_title}")
            continue

        if command == "контекст" or command.startswith("контекст "):
            _requested_domain = question[len("контекст"):].strip()
            if not _requested_domain:
                print("\nТекущий контекст: "
                      + project_context.domain_label(_active_chat_domain)
                      + f" ({_active_chat_domain})")
                print("Доступные домены:")
                for _domain in project_context.list_domains():
                    print(f"  {_domain['id']} — {_domain['label']}")
                print("Изменение: контекст <идентификатор или название>")
                continue
            _normalized_domain = project_context.normalize_domain(_requested_domain)
            if _normalized_domain is None:
                print("\n⚠ Неизвестный домен. Контекст не изменён.")
                continue
            if not chat_system.set_chat_context_domain(_active_chat_id, _normalized_domain):
                print("\n⚠ Не удалось сохранить контекст чата.")
                continue
            _active_chat_domain = _normalized_domain
            if isinstance(_active_chat, dict):
                _active_chat["context_domain"] = _normalized_domain
            print(f"\nКонтекст чата: {project_context.domain_label(_active_chat_domain)}")
            continue

        if command.startswith("чат название "):
            _new_title = question[len("чат название "):].strip()
            if not _new_title:
                print("\n⚠ Укажи новое название: «чат название Новое имя»")
                continue
            if not _active_chat_id:
                print("\n⚠ Нет активного чата.")
                continue
            if not chat_system.rename_chat(_active_chat_id, _new_title):
                print("\n⚠ Не удалось переименовать.")
                continue
            _active_chat_title = _new_title
            if _active_chat and isinstance(_active_chat, dict):
                _active_chat["title"] = _new_title
            print(f"\n📁 Активный чат переименован: {_active_chat_title}")
            continue

        if command.startswith("чат ") and len(question) > 4:
            _arg = question[4:].strip()
            _chats = chat_system.list_chats()
            if not _chats:
                print("\n📭 Чатов нет. Создай: «новый чат Название»")
                continue
            if not _arg.isdigit():
                print("\n⚠ Укажи номер чата: «чат N». Текущий список — «чаты»")
                continue
            _idx = int(_arg) - 1
            if _idx < 0 or _idx >= len(_chats):
                print(f"\n⚠ Номер вне диапазона 1..{len(_chats)}")
                continue
            _target_id = _chats[_idx].get("id")
            if not _target_id:
                print("\n⚠ Некорректная запись в index.")
                continue
            _loaded = chat_system.load_chat(_target_id)
            if not _loaded:
                print("\n⚠ Не удалось загрузить чат.")
                continue
            _sys_msg = next((m for m in messages if m.get("role") == "system"), None)
            if _sys_msg is None:
                print("\n⚠ Не найдено system-сообщение. Операция отменена.")
                continue
            if not chat_system.set_active_chat(_target_id):
                print("\n⚠ Не удалось переключить active chat.")
                continue
            _active_chat = _loaded
            _active_chat_id = _loaded.get("id")
            _active_chat_title = _loaded.get("title") or "Новый чат"
            _active_chat_created_at = _loaded.get("created_at")
            _active_chat_domain = _loaded.get("context_domain", "general")
            messages.clear()
            messages.append(_sys_msg)
            for _m in (_loaded.get("messages") or []):
                if _m.get("role") != "system":
                    messages.append(_m)
            _hist_count = len(messages) - 1
            print(f"\n📁 Открыт чат: {_active_chat_title}  ({_hist_count} сообщ.)")
            continue

        # ----------------------------------------------------
        # TASK MANAGER — постоянное состояние и восстановление задач
        # ----------------------------------------------------

        if command in {"задачи", "tasks"}:
            try:
                _tasks = task_manager.list_tasks()
                if not _tasks:
                    print("\n📭 Список задач пуст. Создай: задача создать <название>")
                else:
                    _labels = {"pending": "ожидает", "active": "активна",
                               "completed": "завершена", "interrupted": "прервана"}
                    print("\nЗАДАЧИ")
                    for _task in _tasks:
                        print(f"  {_task['id']} [{_labels[_task['status']]}] {_task['title']}")
            except task_manager.TaskManagerError as _error:
                print(f"\n⚠️ Ошибка хранилища задач: {_error}")
            continue

        if command.startswith("задача создать "):
            _title = question[len("задача создать "):].strip()
            try:
                _created = task_manager.create_task(_title)
                print(f"\n✅ Создана задача {_created['id']}: {_created['title']}")
            except task_manager.TaskManagerError as _error:
                print(f"\n⚠️ Не удалось создать задачу: {_error}")
            continue

        if command.startswith("задача прогресс "):
            _rest = question[len("задача прогресс "):].strip()
            _task_id, _sep, _note = _rest.partition(" ")
            if not _sep or not _note.strip():
                print("\n⚠️ Формат: задача прогресс <ID> <описание последнего шага>")
            else:
                try:
                    _updated = task_manager.update_progress(_task_id, note=_note)
                    print(f"\n💾 Точка продолжения сохранена для {_updated['id']}")
                except task_manager.TaskManagerError as _error:
                    print(f"\n⚠️ Не удалось сохранить прогресс: {_error}")
            continue

        if command.startswith("задача шаг начать "):
            _rest = question[len("задача шаг начать "):].strip()
            _parts = _rest.split(maxsplit=1)
            if len(_parts) != 2:
                print("\n⚠️ Формат: задача шаг начать <ID задачи> <ID шага>")
            else:
                try:
                    _task = task_manager.get_task(_parts[0])
                    if _task.get("status") != "active":
                        raise task_manager.TaskManagerError("Сначала активируй задачу: задача продолжить <ID>")
                    if not isinstance(_task.get("plan"), dict):
                        raise task_manager.TaskManagerError("У задачи нет сохранённого плана")
                    planner.start_step(_task["plan"], _parts[1])
                    task_manager.update_progress(
                        _parts[0], note=f"В работе шаг {_parts[1]}", plan=_task["plan"]
                    )
                    print(f"\n▶️ Шаг {_parts[1]} отмечен как выполняемый")
                except (task_manager.TaskManagerError, planner.PlanValidationError) as _error:
                    print(f"\n⚠️ Не удалось начать шаг: {_error}")
            continue

        if command.startswith("задача шаг завершить "):
            _rest = question[len("задача шаг завершить "):].strip()
            _parts = _rest.split(maxsplit=2)
            if len(_parts) != 3:
                print('\n⚠️ Формат: задача шаг завершить <ID задачи> <ID шага> <JSON результатов критериев>')
            else:
                try:
                    _task = task_manager.get_task(_parts[0])
                    if _task.get("status") != "active":
                        raise task_manager.TaskManagerError("Сначала активируй задачу: задача продолжить <ID>")
                    if not isinstance(_task.get("plan"), dict):
                        raise task_manager.TaskManagerError("У задачи нет сохранённого плана")
                    _criterion_results = json.loads(_parts[2])
                    planner.complete_step(_task["plan"], _parts[1], _criterion_results)
                    task_manager.update_progress(
                        _parts[0], note=f"Завершён шаг {_parts[1]}", plan=_task["plan"]
                    )
                    print(f"\n✅ Шаг {_parts[1]} завершён; состояние плана сохранено")
                except (task_manager.TaskManagerError, planner.PlanValidationError, json.JSONDecodeError) as _error:
                    print(f"\n⚠️ Не удалось завершить шаг: {_error}")
            continue

        if command.startswith("задача продолжить ") or command.startswith("продолжить задачу "):
            _prefix = "задача продолжить " if command.startswith("задача продолжить ") else "продолжить задачу "
            _task_id = question[len(_prefix):].strip()
            try:
                _task = task_manager.start_task(_task_id)
                print(f"\n▶️ Продолжаю: {_task['title']} [{_task['status']}]")
                if _task.get("progress_note"):
                    print(f"Последняя точка: {_task['progress_note']}")
                if _task.get("checkpoint"):
                    print(f"Контрольная точка: {json.dumps(_task['checkpoint'], ensure_ascii=False)}")
                if _task.get("plan"):
                    print(planner.format_plan(_task["plan"]))
            except task_manager.TaskManagerError as _error:
                print(f"\n⚠️ Не удалось продолжить задачу: {_error}")
            continue

        if command.startswith("задача начать "):
            _task_id = question[len("задача начать "):].strip()
            try:
                _task = task_manager.start_task(_task_id)
                print(f"\n▶️ Задача активна: {_task['title']}")
            except task_manager.TaskManagerError as _error:
                print(f"\n⚠️ Не удалось начать задачу: {_error}")
            continue

        if command.startswith("задача прервать "):
            _task_id = question[len("задача прервать "):].strip()
            try:
                _task = task_manager.interrupt_task(_task_id)
                print(f"\n⏸ Задача прервана: {_task['title']}")
            except task_manager.TaskManagerError as _error:
                print(f"\n⚠️ Не удалось прервать задачу: {_error}")
            continue

        if command.startswith("задача завершить "):
            _task_id = question[len("задача завершить "):].strip()
            try:
                _task = task_manager.complete_task(_task_id)
                print(f"\n✅ Задача завершена: {_task['title']}")
            except task_manager.TaskManagerError as _error:
                print(f"\n⚠️ Не удалось завершить задачу: {_error}")
            continue

        if command.startswith("задача "):
            _task_id = question[len("задача "):].strip()
            if not _task_id:
                print("\nКоманды: задачи | задача создать <название> | задача <ID> | задача продолжить <ID> | задача прогресс <ID> <текст> | задача прервать <ID> | задача завершить <ID>")
            else:
                try:
                    _task = task_manager.get_task(_task_id)
                    print(f"\nЗАДАЧА {_task['id']} — {_task['title']}")
                    print(f"Статус: {_task['status']} | Создана: {_task['created_at']}")
                    if _task.get("details"):
                        print(f"Описание: {_task['details']}")
                    if _task.get("progress_note"):
                        print(f"Последняя точка: {_task['progress_note']}")
                    if _task.get("checkpoint"):
                        print(f"Контрольная точка: {json.dumps(_task['checkpoint'], ensure_ascii=False)}")
                    if _task.get("plan"):
                        print(planner.format_plan(_task["plan"]))
                except task_manager.TaskManagerError as _error:
                    print(f"\n⚠️ {_error}")
            continue

        # ----------------------------------------------------
        # ПАМЯТЬ
        # ----------------------------------------------------

        if command == "память":

            handle_show_memory_command()

            continue

        if command == "память показать":

            handle_show_all_memory_command()

            continue

        if command == "память статус":

            handle_memory_status_command()

            continue

        if command.startswith("память найти "):

            handle_find_memory_command(command)

            continue

        if command in {
            "память очистить",
            "память очистить подтвердить"
        }:

            handle_clear_memory_command(command)

            continue

        if (
            command.startswith("очисти из памяти ")
            or command.startswith("удали из памяти ")
            or command.startswith("забудь из памяти ")
            or command.startswith("забудь ")
            or command.startswith("удали ")
        ):
            handle_delete_memory_command(question, last_memory_entry_id)
            last_memory_entry_id = None
            continue

        # ----------------------------------------------------
        # СБРОС
        # ----------------------------------------------------

        if command in {
            "сброс",
            "reset"
        }:

            handle_reset_command(state)

            continue

        # ----------------------------------------------------
        # MULTI-STEP EXECUTION 1.4
        if command.startswith("исполнить задача "):
            _execution_task_id = question[len("исполнить задача "):].strip()
            if not _execution_task_id:
                print("\n⚠ Укажи ID: исполнить задача <ID>")
            else:
                run_brain_multistep_execution(task_id=_execution_task_id)
            continue

        if command == "исполнить" or command.startswith("исполнить "):
            _execution_goal = question[len("исполнить"):].strip()
            if not _execution_goal:
                print("\n⚠ Укажи цель: исполнить <описание задачи>")
            else:
                run_brain_multistep_execution(goal=_execution_goal)
            continue

        # PLANNER — явная команда построения плана (без исполнения)
        # ----------------------------------------------------

        _planner_goal = None
        if command == "план":
            print("\n⚠ Укажи цель: план <описание задачи>")
            continue
        if command.startswith("план "):
            _planner_goal = question[5:].strip()
            if not _planner_goal:
                print("\n⚠ Укажи цель: план <описание задачи>")
                continue

        # ----------------------------------------------------
        # ОПРЕДЕЛЯЕМ ЗАДАЧУ
        # ----------------------------------------------------

        task = detect_task(
            _planner_goal or question
        )

        # print()

        # print(
        #     f"Тип задачи: {task.upper()}"
        # )


        answered = False

        # ----------------------------------------------------
        # FALLBACK ПО МОДЕЛЯМ
        # ----------------------------------------------------

        # ----------------------------------------------------
        # MODEL CONTROLLER
        # ----------------------------------------------------

        route = controller_route(task)

        if not route:
            print()
            print("⚠ Модель не выбрана контроллером.")
            continue

        model_id = route.get("model")
        layer = route.get("layer")

        # Планирование отделено от обычного Tool Bridge: модель получает
        # только запрос на JSON-план и не получает инструменты исполнения.
        if _planner_goal:
            _plan_messages = [
                {"role": "system", "content": planner.PLAN_SYSTEM_PROMPT},
                {"role": "user", "content": f"Построй план для цели:\n{_planner_goal}"},
            ]
            _plan_ok, _plan_result = controller_execute(
                route, _plan_messages, tools=None
            )
            if not _plan_ok:
                print(
                    "\n⚠ Не удалось построить план: "
                    + str(_plan_result.get("error", "MODEL_REQUEST_FAILED"))
                )
                continue
            try:
                _plan = planner.parse_plan_response(
                    _plan_result.get("answer", ""), _planner_goal
                )
                try:
                    _saved_task = task_manager.create_task(
                        _planner_goal, details="План создан командой Brain", plan=_plan
                    )
                except task_manager.TaskManagerError as _save_error:
                    _saved_task = None
                    print(f"\n⚠️ План сформирован, но не сохранён: {_save_error}")
                print("\n" + planner.format_plan(_plan))
                if _saved_task:
                    print(f"\n💾 План сохранён как задача {_saved_task['id']}. Продолжение: задача продолжить {_saved_task['id']}")
            except planner.PlanValidationError as _plan_error:
                print(f"\n⚠ Модель вернула некорректный план: {_plan_error}")
            continue

        # print()
        # print(f"Модель: {model_id}")
        # print(f"Слой: {layer}")
        # print(f"Lock: {route.get('lock_type')}")

        # ----------------------------------------------------
        # КОНТЕКСТ ПАМЯТИ
        # ----------------------------------------------------

        # --- однозначный кандидат для ссылочных команд удаления ---
        last_memory_entry_id = None
        try:
            _q_words = _normalize_words(question)
            if _q_words:
                _entries = _load_raw().get("entries", [])
                _scored = []
                for _e in _entries:
                    _t = str(_e.get("text", ""))
                    if len(_t) > 300:
                        continue
                    _s = _score_entry(_e, _q_words, question)
                    if _s > 0:
                        _scored.append((_s, _e))
                if _scored:
                    _scored.sort(
                        key=lambda x: (
                            -x[0],
                            -x[1].get("importance", 5),
                            x[1].get("timestamp", ""),
                        )
                    )
                    _top = _scored[0][0]
                    _cands = [e for s, e in _scored if s == _top]
                    if len(_cands) == 1:
                        last_memory_entry_id = _cands[0].get("id")
        except Exception:
            last_memory_entry_id = None

        memory_context = get_relevant_memory(question)

        if memory_context:
            messages.append({
                "role": "system",
                "name": "memory",
                "content": memory_context,
            })

        # Подгружаем только прошлые чаты из домена активного чата.
        # Текущий чат исключён; retrieval read-only и ограничен по размеру.
        _chat_history_context = context_personalization.build_chat_history_context(
            question,
            context_domain=_active_chat_domain,
            active_chat_id=_active_chat_id,
        )
        if _chat_history_context:
            messages.append({
                "role": "system",
                "name": "chat_recall",
                "content": _chat_history_context,
            })

        # Навыки выбираются для каждого запроса; их текст остаётся недоверенной справкой.
        _selected_skills = skills_manager.select_skills(question)
        _skill_context = skills_manager.render_skill_context(_selected_skills)
        if _skill_context:
            messages.append({
                "role": "system",
                "name": "skill_guidance",
                "content": _skill_context,
            })

        messages.append({
            "role": "user",
            "content": question
        })

        # Гейт бэкенда: суммаризация — LOCAL-фича; API/Gemini/неизвестный слой -> False
        trim_history(messages, allow_summary=(layer == "LOCAL"))

        state["total_requests"] += 1

        # ----------------------------------------------------
        # CONTROLLER EXECUTE
        # ----------------------------------------------------

        ok, result = execute_with_fallback(
            task,
            route,
            messages
        )

        # ----------------------------------------------------
        # РЕЗУЛЬТАТ
        # ----------------------------------------------------

        if ok:
            answer = result["answer"]
            actual_model = result["model"]
            provider = result.get("provider", "unknown")
            elapsed = result["time"]

            state["active_model"] = actual_model
            state["active_provider"] = provider
            state["successful_requests"] += 1

            stats = get_model_stats(actual_model)
            stats["success"] += 1
            stats["total_time"] += elapsed

            save_stats_debounced()

            if model_id == PRIMARY_MODEL:
                state["last_glm_failure"] = 0

            log_decision(
                task=task,
                layer=layer,
                model_id=model_id,
                actual_model=actual_model,
                ok=True,
                elapsed=elapsed,
            )

            _model_short_names = {
                "nvidia/nemotron-3-super-120b-a12b:free": "Nemotron 3 Super",
                "nvidia/nemotron-3-super-120b-a12b": "Nemotron 3 Super",
                "qwen/qwen3-4b-instruct": "Qwen 3 4B",
                "qwen/qwen2.5-3b-instruct": "Qwen 2.5 3B",
                "/storage/emulated/0/модели/Qwen3-4B-Instruct-2507-Q4_K_M.gguf": "Qwen 3 4B",
                "/storage/emulated/0/модели/Qwen2.5-3B-Instruct.Q4_K_M.gguf": "Qwen 2.5 3B",
            }
            _model_display = _model_short_names.get(
                actual_model,
                actual_model.split("/")[-1].replace(":free", "")
            )

            print("─" * 64)
            print(f"✓ Готово · {elapsed:.2f} сек. · {_model_display}")
            print("─" * 64)
            print()

            # P1.2: Verifier v2 — observe only, не влияет на поведение.
            try:
                _vr = verifier.verify_text_response(answer)
                _vr_ts = time.strftime("%Y-%m-%d %H:%M:%S")
                _vr_errors = _vr.get("errors") or "-"
                _vr_warnings = _vr.get("warnings") or "-"
                _vr_reasons = _vr.get("reasons") or "-"
                _vr_stats = _vr.get("stats") or {}
                _vr_line = (
                    f"{_vr_ts} | VERIFY_TEXT | "
                    f"category={_vr.get('category')} | "
                    f"ok={_vr.get('ok')} | "
                    f"length={_vr_stats.get('length', 0)} | "
                    f"lines={_vr_stats.get('lines', 0)} | "
                    f"words={_vr_stats.get('words', 0)} | "
                    f"errors={_vr_errors} | "
                    f"warnings={_vr_warnings} | "
                    f"reasons={_vr_reasons}\n"
                )
                with open(BRAIN_LOG_FILE, "a", encoding="utf-8") as _vf:
                    _vf.write(_vr_line)
            except Exception:
                pass  # observe-only: не роняем основной поток

            print(answer)

            # VOICE ROUND-TRIP: озвучка ответа, если вход был голосовым
            if voice_input:
                try:
                    _tts = tool_execute("tts_speak", {"text": answer[:512]})
                    if not _tts.get("ok"):
                        print(f"  ⚠ TTS не выполнен: {_tts.get('error')}")
                except Exception as _e:
                    print(f"  ⚠ TTS сбой: {_e}")

            # ------------------------------------------------
            # FACT EXTRACTION 2.0 — Ворота качества
            # ------------------------------------------------

            try:
                existing_memory_entries = load_entries_for_fact_extraction()
            except Exception as memory_error:
                print(
                    "\n⚠ Память недоступна или повреждена; "
                    f"извлечение фактов пропущено без изменения памяти: {memory_error}"
                )
                extraction_result = {"action": "IGNORE"}
            else:
                extraction_result = process_extraction_flow(
                    question, answer, existing_memory_entries
                )

            if extraction_result["action"] == "SAVE_PRIMARY":
                result = add_memory(
                    text=extraction_result["fact"]["text"],
                    category=extraction_result["fact"]["category"],
                    source=extraction_result["fact"]["source"],
                    confidence=extraction_result["fact"]["confidence"],
                )
                print(f"🧠 Память: {result}")
            elif extraction_result["action"] == "UPDATE_PRIMARY":
                result = update_memory_entry(extraction_result["target_entry_id"], extraction_result["fact"])
                print(f"🧠 Память: {result}")
            elif extraction_result["action"] in ("ENQUEUE", "ENQUEUE_UPDATE"):
                queued_fact = dict(extraction_result["fact"])
                if extraction_result["action"] == "ENQUEUE_UPDATE":
                    queued_fact["target_entry_id"] = extraction_result["target_entry_id"]
                    queued_fact["expected_old_text"] = extraction_result["expected_old_text"]
                if save_candidate(queued_fact):
                    print(f"💡 Факт добавлен в очередь подтверждения: «{queued_fact['text']}»")
                else:
                    print("⚠ Не удалось записать факт в очередь кандидатов; основная память не изменялась.")

            # ------------------------------------------------
            # ДОБАВЛЯЕМ ОТВЕТ В ИСТОРИЮ
            # ------------------------------------------------

            messages.append({
                "role": "assistant",
                "content": answer
            })

            # Гейт бэкенда: ответ уже показан, простой; только LOCAL-суммаризация
            trim_history(messages, allow_summary=(layer == "LOCAL"))

            # Patch 2.2: сохранить завершённый exchange в active chat.
            # Исключаем transient (memory, chat_recall), system prompt оставляем.
            if _active_chat_id:
                _persist_messages = [
                    _m for _m in messages
                    if not (_m.get("role") == "system"
                            and _m.get("name") in ("memory", "chat_recall"))
                ]
                chat_system.save_chat({
                    "id": _active_chat_id,
                    "title": _active_chat_title,
                    "messages": _persist_messages,
                    "created_at": _active_chat_created_at,
                    "context_domain": _active_chat_domain,
                })

            answered = True

        else:
            error = result.get(
                "error",
                "Неизвестная ошибка"
            )
            # Контракт model-результата (аудит №17): error_type через существующий классификатор
            _err_type = classify_error(error)
            result["error_type"] = _err_type

            log_decision(
                task=task,
                layer=layer,
                model_id=model_id,
                actual_model=None,
                ok=False,
                elapsed=0.0,
                error=error,
            )

            print()
            # P0.6: humanized user-facing errors, internal codes unchanged
            if _err_type == "RATE_LIMIT":
                print("⚠ Достигнут доступный лимит модели. Пробую другую модель...")
            elif _err_type == "TIMEOUT":
                print("⚠ Модель не ответила вовремя. Пробую другой вариант...")
            elif _err_type in ("NETWORK_ERROR", "SSL_ERROR"):
                print("⚠ Не удалось соединиться с моделью. Пробую другой вариант...")
            elif _err_type == "LOCAL_ERROR":
                print("⚠ Локальная модель недоступна. Пробую другой вариант...")
            elif _err_type == "MODEL_ERROR":
                print("⚠ Модель вернула пустой ответ. Пробую другую модель...")
            else:
                print("⚠ Модель временно недоступна. Пробую другую модель...")

            # Сбрасываем lock при ошибке, чтобы не зацикливаться на нерабочей модели
            failed_model = result.get("model") or model_id
            if state.get("model_lock") == failed_model:
                state["model_lock"] = None
                state["model_lock_type"] = None
                state["model_lock_layer"] = None

# ============================================================
# [17] LOCAL MODEL ROUTER — ЛОКАЛЬНАЯ МАРШРУТИЗАЦИЯ
# ============================================================

# LOCAL MODELS подключены: qwen3 (8085), granite (8088) — см. LOCAL_MODEL_SERVICES
# к MAIN LOOP. Наличие сервисов не влияет на текущий OpenRouter routing.

LOCAL_MODEL_SERVICES = {
    "qwen25_3b": {
        "url": "http://127.0.0.1:8088",
        "model": "/storage/emulated/0/модели/Qwen2.5-3B-Instruct.Q4_K_M.gguf",
        "task": "fast_text",
        "enabled": True,
    },
    "qwen3": {
        "url": "http://127.0.0.1:8085",
        "model": "/storage/emulated/0/модели/Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
        "task": "general",
        "enabled": True,
    },
}


def voice_cmd():
    """Голосовой ввод: termux-speech-to-text -> текст (None при ошибке).
    Аудит #11 VOICE: STT выполняется ДО модели; текст идёт в обычный pipeline."""
    print("🎤 Слушаю... (скажи фразу, пауза = конец)")
    try:
        proc = subprocess.run(
            ["termux-speech-to-text"],
            capture_output=True, text=True, timeout=60,
        )
    except FileNotFoundError:
        print("⚠ termux-speech-to-text не найден (пакет termux-api).")
        return None
    except subprocess.TimeoutExpired:
        print("⏱ Таймаут: речь не распознана за 60 с.")
        return None
    except Exception as e:
        print(f"⚠ Ошибка STT: {e}")
        return None
    if proc.returncode != 0:
        print(f"⚠ STT завершился с кодом {proc.returncode}.")
        return None
    text = (proc.stdout or "").strip()
    if not text:
        print("⚠ Пустой результат распознавания.")
        return None
    return text


def brief_cmd():
    """Брифинг: дата + свежие записи памяти. Детерминированный, без модели, read-only."""
    from datetime import datetime as _dt
    print("\n" + "=" * 64)
    print(f"БРИФИНГ — {_dt.now().strftime('%d.%m.%Y %H:%M')}")
    print("=" * 64)
    try:
        entries = _load_raw().get("entries", [])
    except Exception as e:
        print(f"  ⚠ Память недоступна: {e}")
        return
    print(f"  Записей в памяти: {len(entries)}")
    if not entries:
        print("  Память пуста.")
        return
    recent = sorted(entries, key=lambda e: str(e.get("timestamp", "")), reverse=True)[:7]
    print("\nСвежие записи:")
    for e in recent:
        text = " ".join(str(e.get("text", "")).split())
        print(f"  • [{e.get('category', '?')}|imp {e.get('importance', '?')}] {text[:110]}")
    print()

def selfcheck_cmd():
    """Read-only самодиагностика: память, реестр, локальные модели, лог, диск."""
    import shutil

    print("\n" + "=" * 64)
    print("SELFCHECK — самодиагностика окружения")
    print("=" * 64)

    results = {}

    # 1. ПАМЯТЬ
    try:
        m = status_memory()
        cats = m.get("categories", {})
        print(f"  ✅ Память: version={m.get('version')}, записей={m.get('total')}, категорий={len(cats)}")
        results["memory"] = True
    except Exception as e:
        print(f"  ❌ Память: ошибка загрузки: {e}")
        results["memory"] = False

    # 2. РЕЕСТР (структурная целостность; 19/15/4 — информативно)
    try:
        total = len(REGISTRY.all_tools())
        model_view = len(REGISTRY.get_tools_for_model())
        hidden = total - model_view
        if total > 0 and hidden >= 0:
            print(f"  ✅ Реестр: total={total}, model={model_view}, hidden={hidden}")
            results["registry"] = True
        else:
            print(f"  ❌ Реестр: несогласованные счётчики: total={total}, model={model_view}")
            results["registry"] = False
    except Exception as e:
        print(f"  ❌ Реестр: ошибка: {e}")
        results["registry"] = False

    # 3. ЛОКАЛЬНЫЕ МОДЕЛИ (INFO: сервер опционален, не влияет на итог)
    try:
        for name, svc in get_local_model_services().items():
            if not svc.get("enabled"):
                print(f"  ⚪ {name}: отключён ({svc['url']})")
                continue
            alive = check_local_health(svc, timeout=2)
            mark = "✅" if alive else "⚪"
            state = "отвечает" if alive else "не отвечает (сервер опционален)"
            print(f"  {mark} {name}: {svc['url']} — {state}")
    except Exception as e:
        print(f"  ⚠️ Локальные модели: ошибка проверки: {e}")

    # 4. ЛОГ
    try:
        if os.access(BRAIN_LOG_FILE, os.W_OK):
            print(f"  ✅ Лог: {BRAIN_LOG_FILE} доступен на запись")
            results["log"] = True
        else:
            print(f"  ❌ Лог: {BRAIN_LOG_FILE} недоступен на запись")
            results["log"] = False
    except Exception as e:
        print(f"  ❌ Лог: ошибка: {e}")
        results["log"] = False

    # 5. ДИСК
    MIN_FREE = 500 * 1024 * 1024
    disk_warn = False
    for label, path in (("HOME", os.path.expanduser("~")), ("storage", "/storage/emulated/0")):
        try:
            u = shutil.disk_usage(path)
            free_mb = u.free // (1024 * 1024)
            if u.free >= MIN_FREE:
                print(f"  ✅ Диск {label}: свободно {free_mb} МБ")
            else:
                print(f"  ⚠️ Диск {label}: свободно только {free_mb} МБ (< порога {MIN_FREE // (1024*1024)} МБ)")
                disk_warn = True
        except Exception as e:
            print(f"  ⚠️ Диск {label}: недоступен: {e}")

    print("-" * 64)
    if not all(results.values()):
        print("⚠️ SELFCHECK: ЕСТЬ ПРОБЛЕМЫ (см. ❌ выше)")
    elif disk_warn:
        print("⚠️ SELFCHECK: OK с замечаниями (мало места на диске)")
    else:
        print("🎉 SELFCHECK: OK")
    print("=" * 64)


def get_local_model_services():
    """Возвращает конфигурацию локальных моделей без их запуска."""
    return LOCAL_MODEL_SERVICES


def get_local_model_for_task(task):
    """Возвращает локальную модель для задачи. Проверяет здоровье, если нет — fallback."""
    task_lower = task.lower() if isinstance(task, str) else task
    for service in LOCAL_MODEL_SERVICES.values():
        if service["task"].lower() == task_lower and service["enabled"]:
            if check_local_health(service):
                return service
    # Fallback на granite если целевая модель недоступна или не отвечает
    fallback_name = globals().get("LOCAL_MODEL_FALLBACK")
    if fallback_name and fallback_name in LOCAL_MODEL_SERVICES:
        fb = LOCAL_MODEL_SERVICES[fallback_name]
        if fb.get("enabled") and check_local_health(fb):
            return fb
    return None


def check_local_health(service, timeout=2):
    """Быстрая проверка доступности локального сервера перед основным запросом."""
    try:
        response = requests.get(
            service["url"] + "/health",
            timeout=timeout,
        )
        return response.status_code == 200
    except requests.RequestException:
        try:
            response = requests.get(
                service["url"] + "/v1/models",
                timeout=timeout,
            )
            return response.status_code == 200
        except requests.RequestException:
            return False


def _reset_slot(url, timeout=2):
    """Сбрасывает KV-cache слота при смене модели/контекста."""
    try:
        # Получаем список слотов
        r = requests.get(url + "/slots", timeout=timeout)
        if r.status_code == 200:
            slots = r.json()
            for slot in (slots if isinstance(slots, list) else []):
                sid = slot.get("id")
                if sid is not None:
                    requests.post(
                        url + "/slots/" + str(sid),
                        json={"action": "erase"},
                        timeout=timeout,
                    )
    except Exception:
        pass


def ask_local_model(service, messages, tools=None):
    """Запрос к локальной OpenAI-compatible llama-server."""
    url = service["url"] + "/v1/chat/completions"

    payload = {
        "model": service["model"],
        "messages": messages,
        "stream": False,
    }

    if tools:
        payload["tools"] = tools

    started = time.time()

    response = None
    last_error = None



    for attempt in range(2):
        try:


            response = requests.post(
                url,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json=payload,
                timeout=LOCAL_MODEL_RESPONSE_TIMEOUT,
            )
            break
        except requests.Timeout:
            last_error = "LOCAL_TIMEOUT"
        except requests.RequestException as error:
            last_error = str(error)

    if response is None:
        return False, {
            "error": last_error,
            "time": time.time() - started,
        }

    elapsed = time.time() - started

    if response.status_code != 200:
        return False, {
            "error": f"LOCAL_HTTP_{response.status_code}",
            "time": elapsed,
        }

    try:
        data = response.json()
    except Exception:
        return False, {
            "error": "LOCAL_INVALID_JSON",
            "time": elapsed,
        }

    choices = data.get("choices", [])

    if not choices:
        return False, {
            "error": "LOCAL_EMPTY_CHOICES",
            "time": elapsed,
        }

    message = choices[0].get("message", {})
    answer = message.get("content", "")
    tool_calls = message.get("tool_calls", None)

    if not answer and not tool_calls:
        return False, {
            "error": "LOCAL_EMPTY_RESPONSE",
            "time": elapsed,
        }

    actual_model = data.get(
        "model",
        service["model"],
    )

    return True, {
        "answer": answer,
        "model": actual_model,
        "provider": "local",
        "time": elapsed,
        "tool_calls": tool_calls,
    }



# ============================================================
# [18] MODEL CONTROLLER — ЕДИНАЯ ТОЧКА ВЫБОРА МОДЕЛИ
# ============================================================

LOCAL_MODEL_ALIASES = {
    "granite": "qwen25_3b",
    "fast_local": "qwen25_3b",
    "fast": "qwen25_3b",
    "fast_text": "qwen25_3b",
    "qwen3": "qwen3",
    "general": "qwen3",
    "fallback": "qwen3",
}

# Автокоррекция частых опечаток (маленькая клавиатура телефона)
LOCAL_MODEL_AUTOCORRECT = {
    "granit": "qwen25_3b",
    "grante": "qwen25_3b",
    "qwen": "qwen3",
    "qwen3": "qwen3",
    "fast": "qwen25_3b",
    "local": "qwen25_3b",
}

def autocorrect_local_model(name: str) -> tuple[str, bool]:
    """Возвращает (исправленное_имя, было_исправление)."""
    lower = name.strip().lower()
    # Точное совпадение в словаре
    if lower in LOCAL_MODEL_AUTOCORRECT:
        corrected = LOCAL_MODEL_AUTOCORRECT[lower]
        if corrected != lower:
            return corrected, True
        # Имя уже корректное — не исправляем
        return lower, False
    # Префиксное совпадение ТОЛЬКО если ввод короче 4 символов (защита от ложных срабатываний)
    if len(lower) < 4:
        for key, val in LOCAL_MODEL_AUTOCORRECT.items():
            if key.startswith(lower) and val != lower:
                return val, True
    return name, False



LOCAL_MODEL_ROLES = {
    "qwen25_3b": "FAST_TEXT",
    "qwen3": "GENERAL",
}

# Fallback: если основная модель задачи недоступна, пробуем granite
LOCAL_MODEL_FALLBACK = "qwen25_3b"


def controller_status():
    return {
        "mode": state.get("controller_mode", "AUTO"),
        "model": state.get("model_lock"),
        "lock_type": state.get("model_lock_type"),
        "layer": state.get("model_lock_layer"),
    }


def controller_unlock():
    state["model_lock"] = None
    state["model_lock_type"] = None
    state["model_lock_layer"] = None
    state["controller_mode"] = "AUTO"


def controller_lock_manual(model_id, layer):
    state["controller_mode"] = "MANUAL"
    state["model_lock"] = model_id
    state["model_lock_type"] = "MANUAL"
    state["model_lock_layer"] = layer

    return {
        "model": model_id,
        "layer": layer,
        "lock_type": "MANUAL",
    }


def controller_lock_auto(model_id, layer):
    state["controller_mode"] = "AUTO"
    state["model_lock"] = model_id
    state["model_lock_type"] = "AUTO"
    state["model_lock_layer"] = layer

    return {
        "model": model_id,
        "layer": layer,
        "lock_type": "AUTO",
    }


def controller_find_local(alias):
    key = str(alias).strip().lower()
    service_name = LOCAL_MODEL_ALIASES.get(key)

    if not service_name:
        return None

    service = LOCAL_MODEL_SERVICES.get(service_name)

    if not service or not service.get("enabled"):
        return None

    return service_name, service


def controller_route(task):
    locked_model = state.get("model_lock")
    locked_layer = state.get("model_lock_layer")

    if locked_model:
        return {
            "model": locked_model,
            "layer": locked_layer,
            "lock_type": state.get("model_lock_type"),
            "locked": True,
        }

    if controller_is_local_enabled():
        local_service = get_local_model_for_task(task)

        if local_service:
            local_name = None

            for name, service in LOCAL_MODEL_SERVICES.items():
                if service is local_service:
                    local_name = name
                    break

            if local_name:
                return controller_lock_auto(
                    local_name,
                    "LOCAL",
                )

    candidates = rank_models(task)

    if not candidates:
        return None

    model_id = candidates[0].get("id")

    if not model_id:
        return None

    # Определяем слой: Gemini или обычный API
    route_layer = "API"
    if model_id in GEMINI_MODELS:
        route_layer = "GEMINI"

    return controller_lock_auto(
        model_id,
        route_layer,
    )


def controller_resolve_local(model_name):
    service = LOCAL_MODEL_SERVICES.get(model_name)

    if not service:
        return None

    if state.get("model_lock_type") != "MANUAL" and not service.get("enabled"):
        return None

    return service


def is_transient_error(err):
    """Проверка ошибки на транзиентность (429 или 5xx)."""
    return str(err).startswith(("429", "HTTP_429", "HTTP_5"))


def controller_execute(route, messages, tools=None):
    if not route:
        return False, {
            "error": "NO_MODEL_SELECTED",
        }

    model_id = route.get("model")
    layer = route.get("layer")

    if not model_id or not layer:
        return False, {
            "error": "INVALID_CONTROLLER_ROUTE",
        }

    # === MEMORY_SYS_DEDUP_ALL (Ф1, BUG#11/#43): main аппендит memory-блок
    # каждый ход в одну messages; на API/GEMINI дедупа нет — копии давят
    # бюджет и триггерят срез фактов. Точные дубли system-блоков по content,
    # keep-first; локальная копия — оригинал не мутируется.
    _seen_all = set()
    _dedup_all = []
    for _m in messages:
        if _m.get("role") == "system":
            _c = str(_m.get("content", ""))
            if _c in _seen_all:
                continue
            _seen_all.add(_c)
        _dedup_all.append(_m)
    messages = _dedup_all
    # === /MEMORY_SYS_DEDUP_ALL ===
    # Context Manager: подготовка контекста перед отправкой модели
    try:
        prepared_messages, cm_diag = context_manager.prepare_context(messages, layer)
        _ui_pct = min(round(cm_diag['input_size'] / cm_diag['budget'] * 100, 1), 100)
        print(f"📊 Контекст: {int(round(_ui_pct))}%")
        # Ф3 (BUG#11): телеметрия CM в brain.log ВСЕГДА — механизм log_decision
        # (time.strftime, append utf-8, молча пропускает при ошибке записи).
        try:
            _cm_ts = time.strftime("%Y-%m-%d %H:%M:%S")
            _cm_line = (
                f"{_cm_ts} | INFO  | cm | layer={layer} | "
                f"size={cm_diag.get('input_size')}->{cm_diag.get('output_size')} | "
                f"budget={cm_diag.get('used_pct')}% | "
                f"msgs={cm_diag.get('messages_in')}->{cm_diag.get('messages_out')} | "
                f"trimmed={cm_diag.get('trimmed')}\n"
            )
            with open(BRAIN_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(_cm_line)
        except Exception:
            pass
        messages = prepared_messages
    except Exception as e:
        print(f"⚠️ Context Manager error (fallback to raw): {e}")
        # При ошибке CM — работаем без него, не ломаем запрос

    if layer == "LOCAL":
        service = controller_resolve_local(model_id)
        if not service:
            return False, {
                "error": "LOCKED_LOCAL_MODEL_UNAVAILABLE",
                "model": model_id,
            }

        _local_health = get_model_stats(model_id)
        if _local_health.get("empty_cooldown_until", 0) > time.time():
            return False, {
                "error": "LOCAL_MODEL_IN_COOLDOWN",
                "model": model_id,
            }

        if not check_local_health(service):
            return False, {
                "error": "LOCAL_SERVICE_UNAVAILABLE",
                "model": model_id,
            }

        # LOCAL-память: system-сообщения (в т.ч. память пользователя и базовый
        # промпт) не теряются при слайсе хвоста; хвост = бюджет минус system.
        _sys = [m for m in messages if m.get("role") == "system"]
        # === LOCAL_SYS_DEDUP (фикс LOCAL_SPEED: дубли system-памяти ломают prefix-cache) ===
        _seen_sys = set()
        _dedup_sys = []
        for _m in _sys:
            _c = str(_m.get("content", ""))
            if _c in _seen_sys:
                continue
            _seen_sys.add(_c)
            _dedup_sys.append(_m)
        _sys = _dedup_sys
        # === /LOCAL_SYS_DEDUP ===
        _ns = [m for m in messages if m.get("role") != "system"]
        _keep = max(1, MAX_HISTORY_LOCAL - len(_sys))
        local_messages = _sys + _ns[-_keep:]


        ok, result = ask_local_model(
            service,
            local_messages,
            tools=tools,
        )

        _local_health = get_model_stats(model_id)
        if ok:
            _local_health["empty_streak"] = 0
        else:
            _local_err = result.get("error", "")
            if _local_err in ("LOCAL_EMPTY_CHOICES", "LOCAL_EMPTY_RESPONSE"):
                _local_health["empty_streak"] = _local_health.get("empty_streak", 0) + 1
                if _local_health["empty_streak"] >= 2:
                    _local_health["empty_cooldown_until"] = time.time() + 1800
                    _local_health["last_error"] = "EMPTY_STREAK_COOLDOWN"

        return ok, result

    if layer in ("API", "GEMINI"):
        attempts = []
        if layer == "GEMINI":
            ok, result = ask_gemini_model(model_id, messages, tools=tools)
            if ok:
                return True, result
            attempts.append(_controller_attempt_record("GEMINI", model_id, result))

            # Внутрислойный каскад Gemini: если 429/5xx, перебираем другие модели Gemini
            if is_transient_error(result.get("error")):
                tried_gemini = {str(model_id).strip().lower()}
                chain = GEMINI_FALLBACK_CHAIN if "GEMINI_FALLBACK_CHAIN" in globals() else list(GEMINI_MODELS.keys())
                for fb_gemini in chain:
                    fb_clean = str(fb_gemini).strip().lower()
                    if fb_clean in tried_gemini:
                        continue
                    tried_gemini.add(fb_clean)
                    print("  🔄 Переключаюсь на резервную модель...")
                    ok_fb, res_fb = ask_gemini_model(fb_gemini, messages, tools=tools)
                    if ok_fb:
                        controller_lock_auto(fb_gemini, "GEMINI")
                        return True, res_fb
                    attempts.append(_controller_attempt_record("GEMINI", fb_gemini, res_fb))
                    if not is_transient_error(res_fb.get("error")):
                        break

            # Если ошибка НЕ транзиентная или все Gemini исчерпали квоту
            if not is_transient_error(result.get("error")):
                return False, {**result, "attempts": attempts}
        else:
            ok, result = ask_model(model_id, messages, tools=tools)
            if ok:
                return True, result
            attempts.append(_controller_attempt_record("API", model_id, result))

            # Если ошибка НЕ транзиентная (400, 401 и т.д.) — выходим сразу
            if not is_transient_error(result.get("error")):
                return False, {**result, "attempts": attempts}

        # PRIMARY получил 429/5xx и исчерпал свой слой — запускаем внешний fallback
        tried = {str(model_id).strip().lower()}

        candidates = rank_models("general")

        if not candidates:
            # Если все модели OpenRouter в кулдауне — спасаем запрос через Gemini
            print("  🌐 Переключаюсь на резервный канал...")
            gemini_chain = GEMINI_FALLBACK_CHAIN if "GEMINI_FALLBACK_CHAIN" in globals() else ["gemini-3.7-flash", "gemini-3.5-flash-lite"]
            for g_model in gemini_chain:
                ok_g, res_g = ask_gemini_model(g_model, messages, tools=tools)
                if ok_g:
                    controller_lock_auto(g_model, "GEMINI")
                    return True, res_g
                attempts.append(_controller_attempt_record("GEMINI", g_model, res_g))
            return False, {
                "error": "ALL_MODELS_IN_COOLDOWN",
                "model": model_id,
                "provider": "OpenRouter/Gemini fallback",
                "attempts": attempts,
            }

        for candidate in candidates:
            fallback_id = str(candidate.get("id", "")).strip()

            if not fallback_id:
                continue

            if fallback_id.lower() in tried:
                continue

            tried.add(fallback_id.lower())

            # Резервные модели всегда идут через OpenRouter (ask_model)
            ok, fallback_result = ask_model(
                fallback_id,
                messages,
                tools=tools,
            )

            # Первый успешный ответ — сразу фиксируем и выходим
            if ok:
                controller_lock_auto(fallback_id, "API")
                return True, fallback_result

            # Если кандидат тоже вернул 429 или 5xx — идём к следующему
            attempts.append(_controller_attempt_record("API", fallback_id, fallback_result))
            if is_transient_error(fallback_result.get("error")):
                continue

        return False, {**result, "attempts": attempts}

    return False, {
        "error": "UNKNOWN_CONTROLLER_LAYER",
        "layer": layer,
    }


def controller_switch(model_name):
    key = str(model_name).strip().lower()

    if not key:
        return None

    # Автокоррекция опечаток
    corrected_key, was_corrected = autocorrect_local_model(key)
    if was_corrected:
        print(f"  ✏️  Автокоррекция: '{key}' → '{corrected_key}'")
    lookup_key = corrected_key if was_corrected else key

    local_name = LOCAL_MODEL_ALIASES.get(lookup_key)

    if local_name:
        if local_name not in LOCAL_MODEL_SERVICES:
            return {
                "error": "UNKNOWN_LOCAL_MODEL",
                "model": model_name.strip(),
            }

        return controller_lock_manual(
            local_name,
            "LOCAL",
        )

    free_models = get_free_models()

    free_ids = [
        str(model.get("id", "")).strip()
        for model in free_models
        if model.get("id")
    ]

    matched_id = None

    for candidate_id in free_ids:
        if candidate_id.lower() == key:
            matched_id = candidate_id
            break

    if not matched_id:
        for candidate_id in free_ids:
            if key in candidate_id.lower():
                matched_id = candidate_id
                break

    if not matched_id:
        return {
            "error": "MODEL_NOT_FREE_OR_NOT_FOUND",
            "model": model_name.strip(),
        }

    # Определяем слой: Gemini или обычный API
    model_layer = "GEMINI" if matched_id in GEMINI_MODELS else "API"

    return controller_lock_manual(
        matched_id,
        model_layer,
    )


def controller_handle_model_command(command):
    parts = str(command).strip().split()

    if not parts:
        return None

    command_name = parts[0].lower()

    if command_name == "model":
        if len(parts) == 1:
            return controller_status()

        if parts[1].lower() == "auto":
            stop_local_server()
            controller_unlock()
            return {
                "mode": "AUTO",
                "message": "Lock снят, локальные серверы остановлены",
            }

        return controller_switch(
            " ".join(parts[1:])
        )

    if command_name == "local":
        if len(parts) == 1:
            return controller_status()

        action = parts[1].lower()

        if action == "on":
            controller_set_local_enabled(True)
            return {
                "local_enabled": True,
            }

        if action == "off":
            controller_set_local_enabled(False)
            return {
                "local_enabled": False,
            }

        if action == "status":
            return {
                "local_enabled": controller_is_local_enabled(),
                "model": state.get("model_lock"),
                "layer": state.get("model_lock_layer"),
            }

        if action == "list":
            return {
                "local_models": [
                    {
                        "name": name,
                        "role": LOCAL_MODEL_ROLES.get(name),
                        "enabled": service.get("enabled", False),
                    }
                    for name, service in LOCAL_MODEL_SERVICES.items()
                ]
            }

        if action == "use" and len(parts) >= 3:
            alias = " ".join(parts[2:])
            # Автокоррекция опечаток
            corrected_alias, was_corrected = autocorrect_local_model(alias.lower())
            if was_corrected:
                print(f"  ✏️  Автокоррекция: '{alias}' → '{corrected_alias}'")
                alias = corrected_alias
            key = LOCAL_MODEL_ALIASES.get(alias.lower())

            if not key:
                return {
                    "error": "UNKNOWN_LOCAL_MODEL",
                    "model": alias,
                }

            if not start_local_server(key):
                return {
                    "error": "LOCAL_SERVER_START_FAILED",
                    "model": key,
                }

            return controller_lock_manual(
                key,
                "LOCAL",
            )

        if action == "stop":
            stop_local_server()
            controller_unlock()
            return {
                "message": "Локальные серверы остановлены, lock снят",
            }

    return None


def controller_set_local_enabled(enabled):
    state["local_enabled"] = bool(enabled)


def controller_is_local_enabled():
    # Qwen3 используется как локальный маршрут по умолчанию, если сервер доступен.
    # Явная команда "local off" сохраняет приоритет и отключает локальную маршрутизацию.
    return bool(
        state.get(
            "local_enabled",
            True,
        )
    )


# ============================================================
# [20] TOOL BRIDGE — MODEL ↔ TOOLS
# ============================================================

TOOL_BRIDGE_MAX_ITERATIONS = 5
LOCAL_TOOL_RESULT_MAX_CHARS = 1500
API_TOOL_RESULT_EMERGENCY_MAX = 50000  # Аварийный предел; нормальное сокращение — через Context Manager


def get_tool_definitions():
    """OpenAI-compatible описания инструментов для модели.
    Делегирует ToolRegistry. Динамически регистрирует MCP-tools при первом вызове."""
    global REGISTRY
    # Динамическая регистрация MCP-инструментов (если MCP жив и ещё не зарегистрирован)
    try:
        if mcp_bridge.mcp_is_alive():
            _existing = {t.name for t in REGISTRY.all_tools()}
            mcp_tools = mcp_bridge.mcp_list_tools()
            for name, info in mcp_tools.items():
                if name not in _existing:
                    schema = info.get("inputSchema", {})
                    REGISTRY.register(tool_registry.ToolDefinition(
                        name=name,
                        source=tool_registry.ToolSource.MCP,
                        capability="mcp.dynamic",
                        priority=50,
                        risk=tool_registry.RiskLevel.LOW,
                        description=info.get("description", name),
                        parameters=schema if schema else {"type": "object", "properties": {}},
                    ))
    except Exception:
        pass  # MCP недоступен — работаем без него
    _tools = REGISTRY.get_tools_for_model()
    return [t for t in _tools
            if module_manager.is_enabled(t.get("function", {}).get("name", ""))]

def _get_tool_definitions_legacy_disabled():
    """Старая реализация отключена. Оставлена для справки."""
    defs = [
        {
            "type": "function",
            "function": {
                "name": "shell",
                "description": "Выполнить разрешённую команду Termux.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "Команда Termux для выполнения."
                        }
                    },
                    "required": ["command"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Прочитать содержимое текстового файла из разрешённой директории. Поддерживает чтение диапазона строк через start_line/end_line (1-based, включительно). Если диапазон не указан — читается весь файл. Используй этот инструмент для ЛЮБой задачи, требующей знать содержимое файла: показать текст, посчитать строки/слова/символы, найти фрагмент, проанализировать код и т.д. Всегда вызывай этот инструмент вместо отказа или shell-команд, если нужны данные из файла.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Путь к файлу."
                        },
                        "start_line": {
                            "type": "integer",
                            "description": "Первая строка диапазона (1-based, включительно). Необязательный."
                        },
                        "end_line": {
                            "type": "integer",
                            "description": "Последняя строка диапазона (1-based, включительно). Необязательный."
                        }
                    },
                    "required": ["path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Создать новый файл в разрешённой директории. Перезапись существующего файла запрещена.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Путь нового файла."
                        },
                        "content": {
                            "type": "string",
                            "description": "Содержимое нового файла."
                        }
                    },
                    "required": ["path", "content"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "directory_list",
                "description": "Показать содержимое разрешённой директории. Возвращает файлы и поддиректории.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Путь к директории."
                        }
                    },
                    "required": ["path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "file_search",
                "description": "Найти текстовый фрагмент или слово в файле или директории. Используй этот инструмент для ЛЮБОЙ задачи на поиск текста/строки/константы в файле — не отвечай по памяти, не угадывай наличие или отсутствие текста. Всегда вызывай file_search, если пользователь просит найти что-то в файле, даже если тебе кажется, что ты знаешь ответ.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Текст для поиска."
                        },
                        "path": {
                            "type": "string",
                            "description": "Директория или файл, в котором искать."
                        }
                    },
                    "required": ["query", "path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "file_edit",
                "description": "Точечно заменить один уникальный фрагмент существующего текстового файла. Если найдено не ровно одно совпадение, изменение не выполняется. ВАЖНО: ВСЕГДА вызывай этот инструмент для изменения файлов — не выводи код в текст ответа.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Путь к существующему файлу."
                        },
                        "old_text": {
                            "type": "string",
                            "description": "Точный существующий фрагмент."
                        },
                        "new_text": {
                            "type": "string",
                            "description": "Новый фрагмент."
                        },
                        "test": {
                            "type": "string",
                            "description": "Необязательное имя тест-файла из whitelist (например, test_brain.py). Если указано — после изменения файла запускается targeted test. Используй, когда меняешь код и хочешь автоматически проверить результат."
                        }
                    },
                    "required": ["path", "old_text", "new_text"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "web_fetch",
                "description": "Получить текстовое содержимое веб-страницы по URL. Используется для RAG, проверки документации и актуализации знаний. Возвращает очищенный текст без HTML-тегов.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "URL страницы (http/https)."
                        },
                        "max_chars": {
                            "type": "integer",
                            "description": "Максимальная длина возвращаемого текста (по умолчанию 15000)."
                        }
                    },
                    "required": ["url"]
                }
            }
        },

        {
            "type": "function",
            "function": {
                "name": "read_pdf",
                "description": "Прочитать текст из PDF-файла.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Путь к PDF."
                        }
                    },
                    "required": ["path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "read_docx",
                "description": "Прочитать текст из DOCX-файла.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Путь к DOCX."
                        }
                    },
                    "required": ["path"]
                }
            }
        }
    ]

    # Добавляем MCP-инструменты (только не дублирующие native)
    # Фильтр дубликатов: по имени И по семантике
    _native_names = {t["function"]["name"] for t in defs}
    _mcp_duplicates = {
        "read_text_file", "read_file",       # дублирует native read_file
        "write_file",                         # дублирует native write_file
        "edit_file",                          # дублирует native file_edit
        "list_directory",                     # дублирует native directory_list
        "list_directory_with_sizes",          # дублирует native directory_list
        "search_files",                       # дублирует native file_search
        "read_media_file",                    # нет native аналога, но оставляем
    }
    _skip_mcp = _native_names | _mcp_duplicates
    try:
        import mcp_bridge
        if mcp_bridge.mcp_is_alive():
            mcp_tools = mcp_bridge.mcp_list_tools()
            for name, info in mcp_tools.items():
                if name not in _skip_mcp:
                    # Конвертируем MCP inputSchema → OpenAI parameters
                    schema = info.get("inputSchema", {})
                    defs.append({
                        "type": "function",
                        "function": {
                            "name": name,
                            "description": info.get("description", name),
                            "parameters": schema if schema else {"type": "object", "properties": {}},
                        }
                    })
        # Если MCP не жив — просто пропускаем, native tools работают
    except Exception:
        pass  # MCP недоступен — работаем без него, graceful degradation

    return defs


def tool_bridge_execute_call(tool_call, last_user=""):
    """Разбирает один tool_call и передаёт выполнение в tool_execute()."""
    try:
        function = tool_call.get("function", {})
        tool_name = function.get("name", "")
        raw_arguments = function.get("arguments", "{}")

        if not tool_name:
            return {
                "ok": False,
                "result": None,
                "error": "TOOL_CALL_MISSING_NAME"
            }

        try:
            params = json.loads(raw_arguments)
        except Exception as error:
            return {
                "ok": False,
                "result": None,
                "error": f"INVALID_TOOL_ARGUMENTS: {error}"
            }

        if tool_name == "shell":
            cmd_clean = str(params.get("command", "")).strip()
            # === SECRETS_DENYLIST shell-ветка (№20): секреты не трогаем даже командами
            if _shell_touches_secret(cmd_clean):
                _sec_reason = "SECRET_FILE_DENIED: команда затрагивает файл с секретами"
                try:
                    with open(BRAIN_LOG_FILE, "a", encoding="utf-8") as _lg:
                        _lg.write(f"{SHELL_GATE_LOG} | cmd={cmd_clean!r} | decision=REJECT | reason={_sec_reason} | last_user={last_user!r}\n")
                except Exception:
                    pass
                return {"ok": False, "result": None, "error": _sec_reason}
            # === /SECRETS_DENYLIST shell-ветка ===
            decision, reason = _classify_shell_call(cmd_clean)
            try:
                with open(BRAIN_LOG_FILE, "a", encoding="utf-8") as _lg:
                    _lg.write(f"{SHELL_GATE_LOG} | cmd={cmd_clean!r} | decision={decision} | reason={reason} | last_user={last_user!r}\n")
            except Exception:
                pass
            if decision == "REJECT":
                return {"ok": False, "result": None, "error": reason}
            if decision == "NEEDS_CONFIRM":
                print(f"\n⚠ Модель запрашивает shell-команду ({reason}):")
                print(f"   $ {cmd_clean}")
                _ans = input("Подтвердить выполнение? [y/N]: ").strip().lower()
                if _ans != "y":
                    return {"ok": False, "result": None,
                            "error": ("USER_DENIED: пользователь отклонил выполнение этой команды. "
                                      "Повтор того же действия (включая вариации аргументов) будет "
                                      "заблокирован до конца этого запроса. Предложи альтернативный "
                                      "безопасный способ или ответь без инструментов.")}

        tool_result = tool_execute(tool_name, params)
        verification = verifier.verify_tool_result(tool_name, tool_result)
        if not verification["valid"]:
            return {
                "ok": False,
                "result": None,
                "error": "TOOL_RESULT_CONTRACT_INVALID: " + ", ".join(verification["errors"]),
                "verification": verification,
                "tool": tool_name,
            }
        verified_result = dict(tool_result)
        verified_result["verification"] = verification
        goal_verification = goal_verifier.verify_goal_result(
            last_user, tool_name, params, verified_result
        )
        verified_result["goal_verification"] = goal_verification
        if goal_verification["status"] == "FAIL":
            verified_result["ok"] = False
            goal_error = (
                "GOAL_VERIFICATION_FAILED: "
                + ", ".join(goal_verification["reasons"])
            )
            # Preserve the executor's original failure: Goal Verifier adds
            # classification, but must not hide the actionable root cause.
            execution_error = verified_result.get("error")
            if isinstance(execution_error, str) and execution_error.strip():
                verified_result["error"] = f"{execution_error} | {goal_error}"
            else:
                verified_result["error"] = goal_error
        return verified_result

    except Exception as error:
        return {
            "ok": False,
            "result": None,
            "error": f"TOOL_BRIDGE_EXCEPTION: {error}"
        }


def tool_bridge_log(iteration, tool_call, result):
    try:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")

        _fn = tool_call.get("function") or {}
        _raw_name = _fn.get("name") or ""
        name = "".join(c for c in str(_raw_name) if c.isalnum() or c == "_")[:64] or "<missing>"

        _raw_id = tool_call.get("id", "")
        cid = "".join(c for c in str(_raw_id) if c.isalnum() or c in "_-")[:64] or "-"

        path_log = "-"
        range_log = "-"

        if name == "read_file":
            params = None
            try:
                _args = _fn.get("arguments") or "{}"
                if isinstance(_args, str):
                    params = json.loads(_args)
                elif isinstance(_args, dict):
                    params = _args
            except Exception:
                params = None

            if not isinstance(params, dict):
                path_log = "<invalid-args>"
            else:
                _raw_path = params.get("path")
                if not _raw_path or not isinstance(_raw_path, str):
                    path_log = "<empty>"
                else:
                    try:
                        _exp = os.path.expanduser(_raw_path)
                        _canon = os.path.realpath(_exp)
                        _root = os.path.dirname(os.path.abspath(__file__))
                        _parts = [p for p in _canon.split(os.sep) if p]
                        _secret = False
                        for _comp in _parts:
                            if _comp in self_inspection.SECRET_BASENAMES:
                                _secret = True
                                break
                            _low = _comp.lower()
                            if _low.startswith(".env"):
                                _secret = True
                                break
                            if any(_low.endswith(_sfx) for _sfx in self_inspection.SECRET_SUFFIXES):
                                _secret = True
                                break
                            if any(_sub in _low for _sub in self_inspection.SECRET_SUBSTRINGS):
                                _secret = True
                                break
                        if _secret:
                            path_log = "<secret-name>"
                        elif _canon == _root or _canon.startswith(_root + os.sep):
                            path_log = "./" + os.path.relpath(_canon, _root)
                        else:
                            path_log = "<outside>"
                    except Exception:
                        path_log = "<error>"

                _s = params.get("start_line")
                _e = params.get("end_line")
                if _s is None and _e is None:
                    range_log = "-"
                else:
                    _si = 1
                    _ei = None
                    _bad = False
                    if _s is not None:
                        if isinstance(_s, bool):
                            _bad = True
                        elif isinstance(_s, int):
                            _si = _s
                        elif isinstance(_s, str) and _s.strip().lstrip("-").isdigit():
                            _si = int(_s.strip())
                        else:
                            _bad = True
                    if _e is not None:
                        if isinstance(_e, bool):
                            _bad = True
                        elif isinstance(_e, int):
                            _ei = _e
                        elif isinstance(_e, str) and _e.strip().lstrip("-").isdigit():
                            _ei = int(_e.strip())
                        else:
                            _bad = True
                    if _bad:
                        range_log = "<invalid-range>"
                    else:
                        range_log = str(_si) + "-" + (str(_ei) if _ei is not None else "?")

        ok = bool(result.get("ok"))
        _res = result.get("result")
        rlen = len(_res) if isinstance(_res, str) else "-"

        _err_raw = result.get("error")
        if not _err_raw:
            err = "-"
        else:
            _txt = str(_err_raw)
            _cut = len(_txt)
            for _i, _ch in enumerate(_txt):
                if _ch == ":" or _ch.isspace():
                    _cut = _i
                    break
            _code = _txt[:_cut]
            if _code and (not _code[0].isupper() or not all(c.isupper() or c.isdigit() or c == "_" for c in _code)):
                _code = ""
            err = _code[:40] if _code else "<unknown-error>"

        line = (f"{ts} | TOOL | iter={iteration} | id={cid} | name={name} | "
                f"path={path_log} | range={range_log} | ok={ok} | len={rlen} | err={err}\n")
        with open(BRAIN_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def tool_bridge_has_calls(result):
    """Проверяет, запросила ли модель инструменты."""
    return bool(result.get("tool_calls"))


def build_local_tool_prompt():
    """Текстовое описание инструментов для LOCAL-моделей без
    надёжной нативной поддержки tool calling (обходит зависание
    grammar-парсера llama.cpp на Qwen3)."""
    tools = get_tool_definitions()
    lines = [
        "У тебя есть доступ к инструментам. Если для ответа нужен "
        "инструмент - ответь СТРОГО одним JSON-объектом, без пояснений "
        "и без markdown-обёртки, в формате:",
        '{"name": "<имя_инструмента>", "arguments": {<параметры>}}',
        "",
        "Доступные инструменты:",
    ]
    for tool in tools:
        function = tool.get("function", {})
        name = function.get("name", "")
        description = function.get("description", "")
        params = function.get("parameters", {}).get("properties", {})
        param_names = ", ".join(params.keys())
        lines.append(f"- {name}({param_names}): {description}")
    lines.append("")
    lines.append("Если инструмент не нужен - ответь обычным текстом, без JSON.")
    return "\n".join(lines)


def try_parse_local_tool_request(answer_text):
    """Пытается распознать JSON-запрос инструмента в ответе LOCAL-модели.
    Возвращает (name, arguments_dict) или None для обычного текста."""
    if not answer_text:
        return None

    text = answer_text.strip()

    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()

    if not text.startswith("{"):
        return None

    try:
        data = json.loads(text)
    except Exception:
        return None

    if not isinstance(data, dict):
        return None

    name = data.get("name")
    arguments = data.get("arguments")

    if not name or not isinstance(arguments, dict):
        return None

    return name, arguments


def try_parse_xml_tool_request(answer_text):
    """Парсит XML-формат tool_call от моделей, не поддерживающих нативный tool calling.
    Формат: <tool_call><function=NAME><parameter=KEY>VALUE</parameter></function></tool_call>
    Возвращает список tool_calls или None."""
    if not answer_text or '<tool_call>' not in answer_text:
        return None
    
    import re
    tool_calls = []
    
    # Ищем все блоки <tool_call>...</tool_call>
    pattern = r'<tool_call>(.*?)</tool_call>'
    matches = re.findall(pattern, answer_text, re.DOTALL)
    
    for match in matches:
        # Извлекаем имя функции: <function=NAME>
        func_match = re.search(r'<function=(\w+)>', match)
        if not func_match:
            continue
        func_name = func_match.group(1)
        
        # Извлекаем все параметры: <parameter=KEY>VALUE</parameter>
        param_pattern = r'<parameter=(\w+)>(.*?)</parameter>'
        params = {}
        for param_match in re.finditer(param_pattern, match, re.DOTALL):
            key = param_match.group(1)
            value = param_match.group(2).strip()
            params[key] = value
        
        if params:
            tool_calls.append({
                "id": f"xml-{len(tool_calls)}",
                "function": {
                    "name": func_name,
                    "arguments": json.dumps(params, ensure_ascii=False),
                },
            })
    
    return tool_calls if tool_calls else None


def _authorize_model_tool_call(tool_name, params):
    """Apply the shared autonomy policy and request consent only when required."""
    decision = autonomy_controller.decide(tool_name, params, REGISTRY)
    if decision.decision == autonomy_controller.AutonomyDecision.AUTO:
        if tool_name == "run_tests":
            print("  🧪 Автоматически разрешён запуск тестов (фиксированный whitelist)")
        else:
            print(f"  🔎 Автоматически разрешено (read-only): {tool_name}")
        return True
    if decision.decision == autonomy_controller.AutonomyDecision.BLOCK:
        print(f"  ⛔ Инструмент заблокирован политикой автономности: {tool_name} ({decision.reason})")
        return False

    definition = REGISTRY.get(tool_name)
    risk = definition.risk.value if definition else "UNKNOWN"
    safe_params = {}
    for key, value in (params or {}).items():
        if any(marker in str(key).lower() for marker in (
            "token", "secret", "password", "credential", "api_key", "apikey"
        )):
            safe_params[key] = "<скрыто>"
        else:
            safe_params[key] = value
    preview = json.dumps(safe_params, ensure_ascii=False, default=str)
    if len(preview) > 500:
        preview = preview[:500] + "..."
    print(f"\n⚠ Требуется подтверждение инструмента: {tool_name} | риск: {risk}")
    print(f"Причина: {decision.reason}")
    print(f"Параметры: {preview}")
    try:
        answer = input("Разрешить выполнение? [да/нет]: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        return False
    return answer in ("да", "д", "yes", "y")


def run_with_tools(route, messages, _executed_calls=None, _denied_tools=None, _tool_results=None,
                   allowed_tool_names=None, before_tool_call=None):
    """Выполняет запрос к модели с поддержкой Tool Calling.

    API   - нативный OpenAI-совместимый tool calling (message.tool_calls).
    LOCAL - текстовый протокол: инструменты описаны в system prompt,
            модель возвращает JSON-запрос текстом, парсим сами.
            Так обойдён баг зависания grammar в llama.cpp для Qwen3.

    Цикл: спросить модель → если просит инструмент, выполнить его
    через tool_execute() и вернуть результат модели → повторить,
    пока модель не даст обычный текстовый ответ или не будет
    достигнут TOOL_BRIDGE_MAX_ITERATIONS.

    ИСПРАВЛЕНО (стабилизация Tool Bridge):
    - если модель после результата инструмента отвечает пустым
      content (ok=False, "Пустой ответ модели"), делаем один
      принудительный довопрос с явной инструкцией дать финальный
      текст; если и это не помогает — отдаём пользователю связный
      fallback на основе последнего результата инструмента вместо
      голой ошибки;
    - если лимит итераций исчерпан, но последний инструмент вернул
      результат, даём модели последний шанс сформировать финальный
      ответ (один дополнительный запрос без инструментов) вместо
      немедленного TOOL_BRIDGE_MAX_ITERATIONS_REACHED."""

    layer = route.get("layer")
    working_messages = list(messages)

    if layer == "LOCAL":
        # LOCAL: Tool Calling отключён — железо телефона не тянет
        # промпт+результат инструмента в разумное время (LOCAL_TIMEOUT).
        # LOCAL работает как обычный чат, без инструментов.
        logging.info("[TOOL_BRIDGE] LOCAL mode → tools disabled, direct answer (no CM)")
        return controller_execute(route, working_messages, tools=None)

    tools_for_api = get_tool_definitions()
    if allowed_tool_names is not None:
        allowed_tool_names = set(allowed_tool_names)
        tools_for_api = [
            item for item in tools_for_api
            if item.get('function', {}).get('name') in allowed_tool_names
        ]

    last_tool_result = None
    last_tool_result_data = None
    # P0.1.2: _executed_calls может быть передан извне (execute_with_fallback)
    if _executed_calls is None:
        _executed_calls = set()  # Dedup: (tool_name, args_json) уже выполненных вызовов
    # P0.1.2b: отказ пользователя сохраняется между fallback-попытками.
    if _denied_tools is None:
        _denied_tools = set()
    # P0.1.2c: фактические результаты вызовов разделяются между моделями.
    if _tool_results is None:
        _tool_results = {}

    EMPTY_ANSWER_ERRORS = (
        "Пустой ответ модели",
        "Модель вернула пустой ответ",
    )

    def _guard_final_answer(model_result):
        """Не позволяет финальному тексту объявить неуспешный последний вызов успешным."""
        if not isinstance(last_tool_result_data, dict):
            return model_result

        goal_check = last_tool_result_data.get("goal_verification")
        goal_status = goal_check.get("status") if isinstance(goal_check, dict) else None
        error_text = str(last_tool_result_data.get("error") or "")
        policy_blocked = error_text.startswith((
            "USER_DENIED:",
            "[DENIED-BAN:",
            "AUTONOMY_BLOCKED:",
            "EXECUTION_TOOL_NOT_ALLOWED:",
        ))
        failed = last_tool_result_data.get("ok") is not True and not policy_blocked
        unverified = isinstance(goal_check, dict) and goal_status != "PASS"
        if not (failed or unverified):
            return model_result

        tool_name = str(last_tool_result_data.get("tool_name") or "unknown")
        error = str(last_tool_result_data.get("error") or "")
        error_code = str(last_tool_result_data.get("error_code") or "")
        reasons = goal_check.get("reasons", []) if isinstance(goal_check, dict) else []
        details = []
        if error:
            details.append(f"Причина: {error[:500]}")
        if error_code:
            details.append(f"Код ошибки: {error_code}")
        if goal_status:
            details.append(f"Goal Verifier: {goal_status}")
        if reasons:
            details.append("Причины проверки: " + ", ".join(str(item) for item in reasons[:10]))
        answer = (
            f"Операция не подтверждена: последний вызов инструмента «{tool_name}» "
            "завершился ошибкой или не прошёл проверку. "
            "Я не могу сообщить, что действие выполнено."
        )
        if details:
            answer += "\n" + "\n".join(details)
        guarded = dict(model_result) if isinstance(model_result, dict) else {}
        guarded.update({
            "answer": answer,
            "tool_execution_status": "failed_or_unverified",
            "tool_failure": dict(last_tool_result_data),
            "model_answer_suppressed": True,
        })
        return guarded

    def _process_tool_call(tool_call, iteration, append_to_context=True):
        """Единая точка выполнения: DENIED → cache replay → execute once."""
        nonlocal last_tool_result_data
        _fn = tool_call.get("function", {})
        _tool_name = _fn.get("name", "")
        _call_key = (_tool_name, _fn.get("arguments", ""))
        call_id = tool_call.get("id", "")

        # Отказ пользователя имеет приоритет даже над кэшем точного вызова.
        if _tool_name in _denied_tools:
            _ban_msg = (
                f"[DENIED-BAN: инструмент '{_tool_name}' уже был отклонён "
                "пользователем в этом запросе. Повторные вызовы (с любыми аргументами) "
                "заблокированы. Предложи альтернативный безопасный способ "
                "или ответь без инструментов.]"
            )
            tool_result = {"ok": False, "result": None, "error": _ban_msg}
            content_text = f"ERROR: {_ban_msg}"
            logging.info(f"[TOOL_BRIDGE] DENIED-BAN: {_tool_name} blocked")
            tool_bridge_log(iteration, tool_call, tool_result)

        elif _call_key in _executed_calls:
            cached_result = _tool_results.get(_call_key)
            if cached_result is not None:
                tool_result = cached_result
                content_text = (
                    tool_result.get("result") if tool_result.get("ok")
                    else f"ERROR: {tool_result.get('error')}"
                )
                logging.info(f"[TOOL_BRIDGE] DEDUP-REPLAY: {_tool_name} result reused")
            else:
                content_text = (
                    "[DEDUP: инструмент уже запускался, повторное выполнение запрещено; "
                    "результат предыдущего вызова недоступен.]"
                )
                tool_result = {"ok": True, "result": content_text, "error": None}
                logging.info(f"[TOOL_BRIDGE] DEDUP: {_tool_name} skipped (result unavailable)")
            tool_bridge_log(iteration, tool_call, tool_result)

        else:
            _last_user = ""
            for _m in reversed(working_messages):
                if _m.get("role") == "user":
                    _last_user = str(_m.get("content", ""))[:200]
                    break

            _approval_error = None
            _params = {}
            try:
                _raw_args = _fn.get("arguments", "{}")
                _params = json.loads(_raw_args) if isinstance(_raw_args, str) else _raw_args
                if not isinstance(_params, dict):
                    _params = {}
            except Exception:
                _params = {}

            if allowed_tool_names is not None and _tool_name not in allowed_tool_names:
                _approval_error = "EXECUTION_TOOL_NOT_ALLOWED: инструмент отсутствует в allowlist"
            else:
                _autonomy = autonomy_controller.decide(_tool_name, _params, REGISTRY)
                if _autonomy.decision == autonomy_controller.AutonomyDecision.BLOCK:
                    _approval_error = "AUTONOMY_BLOCKED: " + _autonomy.reason
                elif _autonomy.decision == autonomy_controller.AutonomyDecision.CONFIRM:
                    _approval_handler = before_tool_call or _authorize_model_tool_call
                    try:
                        _approved = _approval_handler(_tool_name, _params)
                    except Exception:
                        _approved = False
                    if _approved is not True:
                        _approval_error = "USER_DENIED: пользователь не подтвердил выполнение инструмента"

            if _approval_error:
                tool_result = {
                    "ok": False,
                    "result": None,
                    "error": _approval_error,
                    "tool": _tool_name,
                }
            else:
                tool_result = tool_bridge_execute_call(tool_call, last_user=_last_user)

            _executed_calls.add(_call_key)
            _tool_results[_call_key] = tool_result

            if not tool_result.get("ok") and "USER_DENIED" in str(tool_result.get("error", "")):
                if _tool_name:
                    _denied_tools.add(_tool_name)
                    logging.info(f"[TOOL_BRIDGE] DENIED: {_tool_name} added to denied_tools")

            tool_bridge_log(iteration, tool_call, tool_result)
            content_text = (
                tool_result.get("result") if tool_result.get("ok")
                else f"ERROR: {tool_result.get('error')}"
            )

        goal_verification = tool_result.get("goal_verification")
        last_tool_result_data = {
            "tool_name": _tool_name,
            "ok": tool_result.get("ok"),
            "error": tool_result.get("error"),
            "error_code": tool_result.get("error_code"),
            "goal_verification": goal_verification,
        }
        if isinstance(goal_verification, dict):
            _goal_status = goal_verification.get("status", "UNCERTAIN")
            _goal_reasons = ", ".join(goal_verification.get("reasons", []))
            content_text = (
                f"{content_text}\n[GOAL_VERIFICATION: {_goal_status}"
                + (f" — {_goal_reasons}" if _goal_reasons else "")
                + "]"
            )

        if append_to_context:
            if layer == "LOCAL":
                local_text = str(content_text)
                if len(local_text) > LOCAL_TOOL_RESULT_MAX_CHARS:
                    local_text = local_text[:LOCAL_TOOL_RESULT_MAX_CHARS] + (
                        "\n... [обрезано для LOCAL, слишком длинный результат]"
                    )
                working_messages.append({
                    "role": "user",
                    "content": (
                        f"[РЕЗУЛЬТАТ ИНСТРУМЕНТА]: {local_text}\n\n"
                        "Ответь пользователю на основе этого результата обычным текстом."
                    ),
                })
            else:
                api_text = str(content_text)
                if len(api_text) > API_TOOL_RESULT_EMERGENCY_MAX:
                    api_text = api_text[:API_TOOL_RESULT_EMERGENCY_MAX] + (
                        "\n... [АВАРИЙНАЯ ОБРЕЗКА: результат превысил 50K, передан частично]"
                    )
                working_messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": api_text,
                })
        return content_text

    for iteration in range(1, TOOL_BRIDGE_MAX_ITERATIONS + 1):
        logging.info(f"[TOOL_BRIDGE] iter {iteration}/{TOOL_BRIDGE_MAX_ITERATIONS} → calling model ({route.get('model', '?')})")

        ok, result = controller_execute(route, working_messages, tools=tools_for_api)

        if not ok:
            error = result.get("error", "")

            if error in EMPTY_ANSWER_ERRORS and last_tool_result is not None:
                # Модель "зависла" пустым ответом после результата инструмента.
                # Один принудительный довопрос с явной инструкцией.
                working_messages.append({
                    "role": "user",
                    "content": (
                        "Дай, пожалуйста, финальный текстовый ответ пользователю "
                        "на основе результата инструмента выше. Без вызова "
                        "инструментов, просто обычный текст."
                    ),
                })

                ok_retry, result_retry = controller_execute(
                    route, working_messages, tools=None
                )

                if ok_retry and (result_retry.get("answer") or "").strip():
                    return True, _guard_final_answer(result_retry)

                # Даже принудительный довопрос не помог — отдаём
                # пользователю связный fallback вместо голой ошибки.
                fallback_text = (
                    "[СЫРОЙ ВЫВОД ИНСТРУМЕНТА — не обработан моделью]\n"
                    "Не удалось получить развёрнутый ответ модели, но "
                    "инструмент отработал. Результат последнего вызова:\n\n"
                    f"{last_tool_result}\n\n"
                    "[КОНЕЦ СЫРОГО ВЫВОДА ИНСТРУМЕНТА]"
                )
                return True, _guard_final_answer({
                    "answer": fallback_text,
                    "model": result.get("model", route.get("model")),
                    "provider": result.get("provider", "fallback"),
                    "time": result.get("time", 0.0),
                })

            return False, result

        answer_text = result.get("answer", "") or ""

        if layer == "LOCAL":
            parsed = try_parse_local_tool_request(answer_text)
            if parsed is None:
                return True, _guard_final_answer(result)
            tool_name, tool_arguments = parsed
            tool_calls = [{
                "id": f"local-{iteration}",
                "function": {
                    "name": tool_name,
                    "arguments": json.dumps(tool_arguments, ensure_ascii=False),
                },
            }]
            working_messages.append({
                "role": "assistant",
                "content": answer_text,
            })
        else:
            # API модели: сначала проверяем нативный tool_calls, затем fallback на XML парсинг
            if tool_bridge_has_calls(result):
                tool_calls = result.get("tool_calls") or []
            else:
                # Fallback: парсим XML <tool_call> из текста ответа
                xml_calls = try_parse_xml_tool_request(answer_text)
                if xml_calls:
                    # Эвристика: если есть существенный текст ПОМИМО XML —
                    # это финальный ответ, а не намеренный tool call.
                    # Предотвращает зацикливание Nemotron на XML в answer.
                    import re as _re
                    _text_without_xml = _re.sub(
                        r'<tool_call>.*?</tool_call>', '', answer_text, flags=_re.DOTALL
                    ).strip()
                    if len(_text_without_xml) > 100:
                        return True, _guard_final_answer(result)
                    tool_calls = xml_calls
                else:
                    logging.info(f"[TOOL_BRIDGE] iter {iteration}: model returned text answer (no tool calls) → DONE")
                    return True, _guard_final_answer(result)
            working_messages.append({
                "role": "assistant",
                "content": answer_text,
                "tool_calls": tool_calls,
            })

        for tool_call in tool_calls:
            last_tool_result = _process_tool_call(tool_call, iteration)


    # Лимит итераций исчерпан. Если последний инструмент дал результат,
    # даём модели последний шанс сформировать финальный ответ.
    if last_tool_result is not None:
        # Единый направляющий промпт для всех слоев (API, GEMINI, LOCAL)
        working_messages.append({
            "role": "user",
            "content": (
                "Лимит шагов анализа исчерпан. "
                "Сформируй итоговый ответ пользователю на основе всех полученных выше данных. "
                "Ответь обычным текстом, не пытайся вызывать новые инструменты."
            ),
        })

        ok_final, result_final = controller_execute(
            route, working_messages, tools=None
        )
        if ok_final and (result_final.get("answer") or "").strip():
            final_answer = result_final.get("answer", "")
            # Патч А: если модель снова вывела XML tool_call в финальном ответе,
            # выполняем его и даём ещё один шанс дать текстовый ответ
            xml_calls = try_parse_xml_tool_request(final_answer)
            if xml_calls:
                for extra_call in xml_calls[:1]:  # только первый вызов
                    extra_content = _process_tool_call(
                        extra_call, TOOL_BRIDGE_MAX_ITERATIONS + 1,
                        append_to_context=False,
                    )
                    if layer != "LOCAL" and len(str(extra_content)) > API_TOOL_RESULT_EMERGENCY_MAX:
                        extra_content = str(extra_content)[:API_TOOL_RESULT_EMERGENCY_MAX] + (
                            "\n... [АВАРИЙНАЯ ОБРЕЗКА: >50K]"
                        )
                    elif layer == "LOCAL" and len(str(extra_content)) > LOCAL_TOOL_RESULT_MAX_CHARS:
                        extra_content = str(extra_content)[:LOCAL_TOOL_RESULT_MAX_CHARS] + (
                            "\n... [обрезано]"
                        )
                    working_messages.append({
                        "role": "user",
                        "content": (
                            f"[РЕЗУЛЬТАТ ДОПОЛНИТЕЛЬНОГО ИНСТРУМЕНТА]: {extra_content}\n\n"
                            "Дай финальный текстовый ответ пользователю на основе всех результатов выше."
                        ),
                    })
                ok_extra, result_extra = controller_execute(
                    route, working_messages, tools=None
                )
                if ok_extra and (result_extra.get("answer") or "").strip():
                    return True, _guard_final_answer(result_extra)
            return True, _guard_final_answer(result_final)

        # Fallback: если модель не смогла дать связный ответ, отдаем результат последнего инструмента
        fallback_text = (
            "Достигнут лимит шагов анализа, но данные были получены. "
            "Результат последнего вызова инструмента:\n\n"
            f"{last_tool_result}"
        )
        return True, _guard_final_answer({
            "answer": fallback_text,
            "model": route.get("model", ""),
            "provider": "fallback",
            "layer": layer,
            "iterations_reached": True,
        })

    return False, {
        "error": "TOOL_BRIDGE_MAX_ITERATIONS_REACHED",
        "provider": "fallback",
        "model": route.get("model", ""),
        "time": 0.0,
    }



# ============================================================
# ============================================================
# [16] ЗАПУСК

# ============================================================


# ============================================================

def execute_with_fallback(task, initial_route, messages, max_attempts=3):
    """Выполняет запрос с автоматическим переключением на резервные модели при сбоях."""
    current_route = initial_route
    last_result = None
    _executed_calls = set()  # P0.1.2: сохраняется между fallback-попытками
    _denied_tools = set()    # P0.1.2b: сохраняется между fallback-попытками
    _tool_results = {}       # P0.1.2c: кэш фактических результатов вызовов

    for attempt in range(1, max_attempts + 1):
        if attempt > 1:
            current_route = controller_route(task)
            if not current_route:
                print("\n⚠ Нет доступных резервных моделей для продолжения.")
                break

        curr_model = current_route.get("model", "unknown")
        ok, result = run_with_tools(current_route, messages,
                                    _executed_calls=_executed_calls,
                                    _denied_tools=_denied_tools,
                                    _tool_results=_tool_results)

        if ok:
            return True, result

        last_result = result
        error = result.get("error", "Неизвестная ошибка")
        _err_type = classify_error(error)

        failed_model = result.get("model") or curr_model
        _f_stats = get_model_stats(failed_model)

        if _err_type == "RATE_LIMIT":
            _f_stats["cooldown_until"] = max(_f_stats.get("cooldown_until", 0), time.time() + MODEL_429_COOLDOWN)
            print(f"\n⚠ Достигнут доступный лимит модели {failed_model}. Переключаюсь на резерв...")
        else:
            _f_stats["cooldown_until"] = max(_f_stats.get("cooldown_until", 0), time.time() + 30)
            _f_stats["last_error"] = str(error)[:200]
            print(f"\n⚠ Сбой модели {failed_model} ({_err_type}). Переключаюсь на резерв...")

        if state.get("model_lock") == failed_model:
            state["model_lock"] = None
            state["model_lock_type"] = None
            state["model_lock_layer"] = None

    return False, (last_result or {"error": "ALL_FALLBACK_MODELS_FAILED"})

# [21] TOOL CONTROLLER — TERMUX (shell execution)
# ============================================================
import subprocess

TOOL_ALLOWED_COMMANDS = (
    "ls", "pwd", "echo", "df", "free", "ps", "wc",
)

# Запрещённые символы для shell-команд (tool_shell, _classify_shell_call).
# shell-operators + control-characters (POSIX: \n — command separator).
FORBIDDEN_SHELL_CHARS = (
    ";", "&", "|", "`", "$", ">", "<",     # shell operators
    "\n", "\r", "\0", "\t", "\v", "\f",    # control characters
)


def truncate_output(text: str, max_lines: int = 60) -> str:
    """Обрезает длинный вывод команды до max_lines строк."""
    if not text:
        return text
    all_lines = text.split("\n")
    if len(all_lines) <= max_lines:
        return text
    shown = "\n".join(all_lines[:max_lines])
    hidden = len(all_lines) - max_lines
    return f"{shown}\n... ещё {hidden} строк(и) скрыто"


def get_command_hint(bad_command, allowed_commands):
    """Спрашивает модель, что пользователь, возможно, имел в виду,
    когда ввёл команду вне белого списка. Возвращает текст-подсказку
    (не выполняет ничего, только совет)."""
    allowed_list = ", ".join(allowed_commands)
    prompt = (
        f"Пользователь в Termux ввёл команду: '{bad_command}'. "
        f"Она не входит в разрешённый список: {allowed_list}. "
        f"Кратко (2-3 предложения, по-русски) предположи, что пользователь "
        f"хотел сделать, и если это похоже на опечатку в разрешённой команде - "
        f"подскажи правильный вариант. Если это не опечатка, а просто "
        f"неразрешённая операция - объясни, что этот инструмент её не поддерживает."
    )
    messages = [{"role": "user", "content": prompt}]

    ok, data = ask_model(PRIMARY_MODEL, messages)

    if not ok and data.get("error") == "429":
        for candidate in get_free_models():
            candidate_id = candidate.get("id") if isinstance(candidate, dict) else candidate
            if not candidate_id or candidate_id == PRIMARY_MODEL:
                continue
            ok, data = ask_model(candidate_id, messages)
            if ok:
                break

    if not ok:
        return None

    return data.get("answer", "").strip()


FILE_READING_CMDS = ("cat", "head", "tail", "grep", "stat")
SHELL_GATE_LOG = "SHELL_GATE"

def _extract_shell_paths(cmd_clean):
    """Кандидаты-пути (аудит #14b): токены с / или ~ — всегда;
    прочие не-флаги — только если существуют на filesystem (относительные тоже).
    Несуществующие без /~ путями НЕ считаются -> ветка WITHOUT_PATH."""
    import os as _os
    toks = cmd_clean.split()[1:]
    out = []
    for t in toks:
        if t.startswith("-"):
            continue
        if "/" in t or t.startswith("~"):
            out.append(t)
            continue
        try:
            if _os.path.exists(_os.path.realpath(_os.path.expanduser(t))):
                out.append(t)
        except Exception:
            pass
    return out

def _path_in_allowed_dirs(p):
    """Та же проверка, что в tool_read_file: realpath+expanduser + префикс FILES_ALLOWED_DIRS."""
    try:
        real = os.path.realpath(os.path.expanduser(p))
    except Exception:
        return False
    return _files_path_allowed(real)

def _shell_touches_secret(cmd: str) -> bool:
    """№20: True, если в shell-команде упоминается секретный файл.
    Проверка по тексту команды (полный путь в shell не раскрывается)."""
    low = cmd.lower()
    for marker in (".env", ".pem", ".key", "credential"):
        if marker in low:
            return True
    return False


def _classify_shell_call(cmd_clean):
    """Классификация model-initiated shell-вызова (аудит #14):
    REJECT / AUTO_OK / NEEDS_CONFIRM."""
    if "\n" in cmd_clean or "\r" in cmd_clean:
        return "REJECT", "MULTILINE_COMMAND_NOT_ALLOWED"
    for ch in FORBIDDEN_SHELL_CHARS:
        if ch in cmd_clean:
            return "REJECT", "SHELL_OPERATORS_NOT_ALLOWED"
    head = cmd_clean.split()[0] if cmd_clean.split() else ""
    paths = _extract_shell_paths(cmd_clean)
    if head in FILE_READING_CMDS:
        if paths and all(_path_in_allowed_dirs(p) for p in paths):
            return "AUTO_OK", "file-read inside allowed dirs"
        if paths:
            return "NEEDS_CONFIRM", "PATH_OUTSIDE_ALLOWED_DIRS: " + " ".join(paths)
        return "NEEDS_CONFIRM", "FILE_READING_WITHOUT_PATH"
    if head in TOOL_ALLOWED_COMMANDS and not paths:
        return "AUTO_OK", "safe whitelist command"
    return "NEEDS_CONFIRM", "COMMAND_NOT_IN_WHITELIST: " + head


def tool_shell(command: str, timeout: int = 15) -> dict:
    """Выполняет shell-команду только из белого списка. Возвращает
    {ok, result, error} — единый контракт для всех будущих инструментов."""
    cmd_clean = command.strip()
    cmd_head = cmd_clean.split()[0] if cmd_clean else ""
    if cmd_head not in TOOL_ALLOWED_COMMANDS:
        return {"ok": False, "result": None,
                "error": f"COMMAND_NOT_ALLOWED: '{cmd_head}'"}
    
    # Явная проверка однострочности (правило shell-безопасности).
    if "\n" in command or "\r" in command:
        return {"ok": False, "result": None,
                "error": "MULTILINE_COMMAND_NOT_ALLOWED"}

    # shell-operators и прочие control-символы.
    for forbidden_char in FORBIDDEN_SHELL_CHARS:
        if forbidden_char in cmd_clean:
            return {"ok": False, "result": None,
                    "error": "SHELL_OPERATORS_NOT_ALLOWED"}
    try:
        proc = subprocess.run(
            command, shell=True, timeout=timeout,
            capture_output=True, text=True
        )
        return {
            "ok": proc.returncode == 0,
            "result": truncate_output(proc.stdout.strip()),
            "error": proc.stderr.strip() if proc.returncode != 0 else None,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "result": None, "error": "TIMEOUT"}
    except Exception as e:
        return {"ok": False, "result": None, "error": f"EXCEPTION: {e}"}


TEST_WHITELIST = (
    "test_brain.py", "test_debounce.py", "test_log.py",
    "test_registry_contract.py", "test_retry.py", "test_tool_bridge.py",
    "test_verifier.py", "test_file_edit_real.py", "test_local_qwen3.py",
    "test_goal_verifier.py",
    "test_p3_2_4_semantic_guardrails.py",
    "test_p3_2_4_5_semantic_guard_safety.py",
    "test_project_context.py",
    "test_chat_recall_domains.py",
    "test_chat_system_domains.py",
    "test_tool_run_tests.py",
    "test_git_readonly.py",
    "test_autonomy_controller.py",
    "test_tool_bridge_autonomy.py",
    "test_p3_2_4_6_ingestion.py",
    "test_fact_frame_extractor.py",
    "test_local_embedding_provider.py",
    "test_p3_2_4_9_provider_integration.py",
)

ENV_SIGNATURES = (
    "ConnectionRefused", "ConnectionError", "ReadTimeout", "ConnectTimeout",
    "HTTP 429", "HTTPError", "OpenRouter HTTP", "LOCAL_SERVICE_UNAVAILABLE",
    "No endpoints found",
)


def _classify_test_fail(output: str) -> str:
    """Env vs code_fail — формализованная ручная матрица (аудиты №5-14)."""
    for sig in ENV_SIGNATURES:
        if sig in output:
            return "environment"
    return "code"


def tool_run_tests(params: dict) -> dict:
    """Test Runner (аудит №16): запуск whitelisted тест-файлов.
    scope=full (все whitelist) или targeted (один test=<имя>). JSON-контракт:
    per_test[{test, ok, rc, elapsed, tail}], env_fails, code_fails."""
    scope = (params.get("scope") or "full").strip().lower()
    test_file = (params.get("test") or "").strip()

    if scope == "targeted":
        if test_file not in TEST_WHITELIST:
            return {"ok": False, "result": None,
                    "error": f"UNKNOWN_TEST: {test_file or '(пусто)'} (whitelist только)"}
        to_run = [test_file]
    elif scope == "full":
        to_run = list(TEST_WHITELIST)
    else:
        return {"ok": False, "result": None, "error": f"BAD_SCOPE: {scope}"}

    per_test, env_fails, code_fails = [], [], []
    for tf in to_run:
        t0 = time.time()
        output = ""
        try:
            proc = subprocess.run(
                [sys.executable, tf],
                capture_output=True, text=True, timeout=180,
            )
            elapsed = round(time.time() - t0, 2)
            output = (proc.stdout or "") + (proc.stderr or "")
            ok = proc.returncode == 0
            tail = output[-200:]
            entry = {"test": tf, "ok": ok, "rc": proc.returncode,
                     "elapsed": elapsed, "tail": tail}
        except subprocess.TimeoutExpired:
            elapsed = round(time.time() - t0, 2)
            output = "TIMEOUT 180s"
            entry = {"test": tf, "ok": False, "rc": -1, "elapsed": elapsed,
                     "tail": output, "timeout": True}
        except Exception as e:
            elapsed = round(time.time() - t0, 2)
            output = f"SPAWN ERROR: {e}"
            entry = {"test": tf, "ok": False, "rc": -1, "elapsed": elapsed,
                     "tail": output}
        per_test.append(entry)
        if not entry["ok"]:
            # Classify only this test's output; never reuse a previous loop iteration.
            classification = _classify_test_fail(output)
            entry["classification"] = classification
            (env_fails if classification == "environment" else code_fails).append(
                {"test": tf, "signature": (entry.get("tail") or "")[:120]})

    failed = sum(1 for e in per_test if not e["ok"])
    return {"ok": failed == 0, "result": {
        "total": len(per_test), "passed": len(per_test) - failed,
        "failed": failed, "env_fails": env_fails, "code_fails": code_fails,
        "per_test": per_test,
    }, "error": None if failed == 0 else f"{failed} failed"}


def tool_notify_user(title: str, message: str) -> dict:
    """System notification via termux-notification (Termux:API).
    Audit #10 DEVICE_TOOLS. List-argv only (no shell), strip + cap 64/512."""
    try:
        title = (title or "").strip()
        message = (message or "").strip()
        if not title or not message:
            return {"ok": False, "result": None, "error": "EMPTY_TITLE_OR_MESSAGE"}
        title = title[:64]
        message = message[:512]
        if any(ord(c) < 32 and c not in "\n\t" for c in title + message):
            return {"ok": False, "result": None, "error": "CONTROL_CHARACTERS"}
        proc = subprocess.run(
            ["termux-notification", "--title", title, "--content", message],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode != 0:
            return {"ok": False, "result": None, "error": f"NOTIFY_RC_{proc.returncode}"}
        return {"ok": True, "result": "notification sent", "error": None}
    except subprocess.TimeoutExpired:
        return {"ok": False, "result": None, "error": "TIMEOUT"}
    except FileNotFoundError:
        return {"ok": False, "result": None, "error": "TERMUX_API_CLI_MISSING"}
    except Exception as e:
        return {"ok": False, "result": None, "error": f"EXCEPTION: {e}"}


def _briefing_conf_get(key, default):
    """Чтение briefing.conf (key=value)."""
    try:
        for line in open("briefing.conf", encoding="utf-8"):
            line = line.strip()
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip().strip('"')
    except Exception:
        pass
    return default


def _briefing_conf_set(key, value):
    """Запись/обновление key=value в briefing.conf (другие строки сохраняются)."""
    lines = []
    try:
        lines = open("briefing.conf", encoding="utf-8").read().splitlines()
    except Exception:
        pass
    out, found = [], False
    for line in lines:
        if line.strip().startswith(key + "="):
            out.append(f'{key}="{value}"')
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f'{key}="{value}"')
    open("briefing.conf", "w", encoding="utf-8").write("\n".join(out) + "\n")


def tool_briefing_set(params: dict) -> dict:
    """Управление брифингом (аудит №13): mode/on/morning_from — запись в briefing.conf.
    Параметры (любая комбинация):
      action: on | off | mode-auto | mode-morning_evening | set-morning <час>"""
    action = (params.get("action") or "").strip().lower()
    if not action:
        return {"ok": False, "result": None, "error": "EMPTY_ACTION"}
    allowed = {"on", "off", "mode-auto", "mode-morning_evening", "set-morning"}
    if action not in allowed:
        return {"ok": False, "result": None,
                "error": f"UNKNOWN_ACTION: {action} (допустимо: {', '.join(sorted(allowed))})"}
    try:
        if action == "on":
            _briefing_conf_set("BRIEFING_ON", "on")
            return {"ok": True, "result": "Брифинг включён.", "error": None}
        if action == "off":
            _briefing_conf_set("BRIEFING_ON", "off")
            return {"ok": True, "result": "Брифинг выключен.", "error": None}
        if action == "mode-auto":
            _briefing_conf_set("BRIEFING_MODE", "auto")
            return {"ok": True, "result": "Режим: auto (утренний, окно с MORNING_FROM).", "error": None}
        if action == "mode-morning_evening":
            _briefing_conf_set("BRIEFING_MODE", "morning_evening")
            return {"ok": True, "result": "Режим: morning_evening (утро + вечер).", "error": None}
        if action == "set-morning":
            h = str(params.get("hour", "")).strip()
            if not h.isdigit() or not (0 <= int(h) <= 23):
                return {"ok": False, "result": None, "error": "BAD_HOUR"}
            _briefing_conf_set("MORNING_FROM", h)
            return {"ok": True, "result": f"Утренний брифинг начиная с {h}:00.", "error": None}
    except Exception as e:
        return {"ok": False, "result": None, "error": f"EXCEPTION: {e}"}


def tool_tts_speak(text: str) -> dict:
    """TTS via termux-tts-speak (Termux:API). List-argv only, strip + cap 512."""
    try:
        text = (text or "").strip()
        if not text:
            return {"ok": False, "result": None, "error": "EMPTY_TEXT"}
        text = text[:512]
        if any(ord(c) < 32 and c not in "\n\t" for c in text):
            return {"ok": False, "result": None, "error": "CONTROL_CHARACTERS"}
        proc = subprocess.run(
            ["termux-tts-speak", text],
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode != 0:
            return {"ok": False, "result": None, "error": f"TTS_RC_{proc.returncode}"}
        return {"ok": True, "result": "speech finished", "error": None}
    except subprocess.TimeoutExpired:
        return {"ok": False, "result": None, "error": "TIMEOUT"}
    except FileNotFoundError:
        return {"ok": False, "result": None, "error": "TERMUX_API_CLI_MISSING"}
    except Exception as e:
        return {"ok": False, "result": None, "error": f"EXCEPTION: {e}"}


def tool_execute(tool_name: str, params: dict) -> dict:
    _mm_status = module_manager.get_status(tool_name)
    if _mm_status == "disabled":
        return {"ok": False, "result": None,
                "error": f"MODULE_DISABLED: {tool_name}"}
    if _mm_status == "indeterminate":
        return {"ok": False, "result": None,
                "error": "MODULE_STATE_INDETERMINATE"}

    if tool_name == "publish_cpa_gadget":
        # Use the bridge shipped with this repository. Do not depend on a
        # separately installed ~/cpa_bot copy whose API may have drifted.
        bridge_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "cpa_brain_bridge.py",
        )
        if not os.path.isfile(bridge_path):
            return {
                "ok": False, "result": None,
                "error": f"CPA_BRIDGE_NOT_FOUND: {bridge_path}",
            }
        try:
            spec = importlib.util.spec_from_file_location(
                "personal_ai_brain_cpa_bridge", bridge_path
            )
            if spec is None or spec.loader is None:
                return {
                    "ok": False, "result": None,
                    "error": "CPA_BRIDGE_LOAD_ERROR",
                }
            bridge = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(bridge)
            res = bridge.publish_cpa_gadget(
                product_url=params.get("product_url", ""),
                title=params.get("title", ""),
                description=params.get("description", ""),
                price=params.get("price", ""),
                image_url=params.get("image_url"),
                dry_run=True,  # Brain never publishes without a separate approved flow.
                confirm_publish=False,
            )
            post_text = res.get("post_text")
            return {
                "ok": res.get("ok", False),
                "result": res.get("result") or post_text,
                "post_text": post_text,
                "error": res.get("error"),
            }
        except Exception as err:
            return {
                "ok": False, "result": None,
                "error": f"CPA_BRIDGE_EXECUTION_ERROR: {str(err)}",
            }
    """Контракт tool-результата (аудит №17): делегирует в impl и
    добавляет tool/elapsed/error_type аддитивно."""
    import time as _t
    _t0 = _t.time()
    result = _tool_execute_impl(tool_name, params)
    try:
        result.setdefault("tool", tool_name)
        result.setdefault("elapsed", round(_t.time() - _t0, 3))
        if result.get("error"):
            if not result.get("error_type"):
                result["error_type"] = classify_error(result["error"])
            # Preserve the machine-readable root cause independently from
            # error classification: lower layers may already set error_type.
            if not result.get("error_code"):
                error_code = goal_verifier.extract_error_code(result["error"])
                if error_code:
                    result["error_code"] = error_code
        elif result.get("ok"):
            result["error_type"] = None
    except Exception:
        pass
    return result


def _tool_execute_impl(tool_name: str, params: dict) -> dict:
    # Native tools are dispatched locally. Only registered MCP tools may
    # reach the MCP bridge; otherwise local-only tools would be misrouted.
    _native_tools = {
        "shell", "read_file", "write_file", "file_edit", "file_search",
        "directory_list", "web_fetch", "read_pdf", "read_docx",
        "notify_user", "tts_speak", "briefing_set", "run_tests",
        "self_inspection", "memory_audit", "git_inspect",
        "tool_catalog", "propose_tool", "self_improvement_report", "record_answer_feedback", "solution_library", "module_improvement",
    }
    # Единая проверка безопасности через Registry (Native + MCP)
    sec_ok, sec_reason = REGISTRY.security_check(tool_name, params)
    if not sec_ok:
        return {"ok": False, "result": None, "error": sec_reason}

    if tool_name not in _native_tools:
        # Graceful degradation: проверяем жив ли MCP
        if not mcp_bridge.mcp_is_alive():
            # Пробуем перезапустить
            if not mcp_bridge.mcp_start():
                return {"ok": False, "result": None, "error": "MCP_SERVER_UNAVAILABLE"}
        result = mcp_bridge.mcp_call(tool_name, params)
        # Если MCP упал во время вызова — помечаем и возвращаем ошибку
        if not result.get("ok") and "not running" in str(result.get("content", "")):
            mcp_bridge.mcp_stop()  # очищаем мёртвый процесс
        # Конвертируем MCP-формат → Tool Bridge формат
        return {
            "ok": result.get("ok", False),
            "result": result.get("content", ""),
            "error": result.get("content", "") if not result.get("ok") else None,
        }
    """Единая точка входа для локальных Native-инструментов."""
    if tool_name == "tool_catalog":
        return {"ok": True, "result": phase4_tool_catalog.build_tool_catalog(REGISTRY), "error": None}
    if tool_name == "propose_tool":
        try:
            proposal = phase4_tool_proposals.create_tool_proposal(
                name=params.get("name"),
                purpose=params.get("purpose"),
                capability=params.get("capability"),
                risk=params.get("risk"),
                execution_scope=params.get("execution_scope"),
                required_permissions=params.get("required_permissions"),
                constraints=params.get("constraints"),
                acceptance_tests=params.get("acceptance_tests"),
            )
            if TOOL_PROPOSAL_MANAGER is None:
                return {"ok": False, "result": None, "error": "PROPOSAL_STORE_UNAVAILABLE"}
            record = TOOL_PROPOSAL_MANAGER.create(proposal)
            return {
                "ok": True,
                "result": {
                    "proposal": proposal,
                    "proposal_record": record,
                    "inert_code_draft": phase4_tool_proposals.render_python_stub(proposal),
                },
                "error": None,
            }
        except (TypeError, ValueError, OSError) as error:
            return {"ok": False, "result": None, "error": f"INVALID_OR_UNPERSISTED_TOOL_PROPOSAL: {error}"}
    if tool_name == "git_inspect":
        return git_readonly.inspect_repo(params)
    if tool_name == "memory_audit":
        return audit_memory()
    if tool_name == "run_tests":
        return tool_run_tests(params)
    if tool_name == "notify_user":
        return tool_notify_user(params.get("title", ""), params.get("message", ""))
    if tool_name == "briefing_set":
        return tool_briefing_set(params)
    if tool_name == "tts_speak":
        return tool_tts_speak(params.get("text", ""))
    if tool_name == "shell":
        return tool_shell(params.get("command", ""))
    if tool_name == "read_file":
        return tool_read_file(
            params.get("path", ""),
            start_line=params.get("start_line"),
            end_line=params.get("end_line"),
        )
    if tool_name == "write_file":
        return tool_write_file(params.get("path", ""), params.get("content", ""))
    if tool_name == "directory_list":
        return tool_directory_list(params.get("path", ""))
    if tool_name == "file_search":
        return tool_file_search(
            params.get("query", ""),
            params.get("path", "")
        )
    if tool_name == "file_edit":
        return tool_file_edit(
            params.get("path", ""),
            params.get("old_text", ""),
            params.get("new_text", ""),
            test=params.get("test")
        )
    if tool_name == "web_fetch":
        return tool_web_fetch(params.get("url", ""), params.get("max_chars", 15000))

    if tool_name == "read_pdf":
        return tool_read_pdf(params.get("path", ""))
    if tool_name == "read_docx":
        return tool_read_docx(params.get("path", ""))
    if tool_name == "self_inspection":
        return self_inspection.collect()
    if tool_name == "self_improvement_report":
        try:
            from self_improvement import collect_diagnostics
            from self_improvement.commands import build_quality_report
            report = collect_diagnostics(registry=REGISTRY)
            try:
                report["quality"] = build_quality_report(MEMORY_FILE)
            except Exception as quality_error:
                report["quality"] = {
                    "status": "UNKNOWN",
                    "error": "QUALITY_HISTORY_UNAVAILABLE: " + type(quality_error).__name__,
                }
            return {"ok": True, "result": report, "error": None}
        except Exception as error:
            return {"ok": False, "result": None, "error": "SELF_IMPROVEMENT_DIAGNOSTICS_FAILED: " + type(error).__name__}
    if tool_name == "record_answer_feedback":
        try:
            from self_improvement.commands import record_answer_feedback
            record = record_answer_feedback(
                MEMORY_FILE,
                params.get("category"),
                params.get("outcome"),
                params.get("evidence_code", ""),
            )
            return {"ok": True, "result": record, "error": None}
        except (TypeError, ValueError, OSError) as error:
            return {"ok": False, "result": None, "error": "ANSWER_FEEDBACK_NOT_RECORDED: " + str(error)}
    if tool_name == "solution_library":
        try:
            from self_improvement.commands import manage_solution_library
            operation = params.get("operation")
            library_params = {key: value for key, value in params.items() if key != "operation"}
            result = manage_solution_library(MEMORY_FILE, operation, library_params)
            return {"ok": True, "result": result, "error": None}
        except (TypeError, ValueError, OSError) as error:
            return {"ok": False, "result": None, "error": "SOLUTION_LIBRARY_OPERATION_FAILED: " + str(error)}
    if tool_name == "module_improvement":
        try:
            from self_improvement.commands import manage_module_improvements
            operation = params.get("operation")
            proposal_params = {key: value for key, value in params.items() if key != "operation"}
            result = manage_module_improvements(MEMORY_FILE, operation, proposal_params)
            return {"ok": True, "result": result, "error": None}
        except (TypeError, ValueError, OSError) as error:
            return {"ok": False, "result": None, "error": "MODULE_IMPROVEMENT_OPERATION_FAILED: " + str(error)}
    return {"ok": False, "result": None, "error": f"UNKNOWN_TOOL: {tool_name}"}
# ============================================================

# ============================================================
# [22] TOOL CONTROLLER — FILES (read-only, уровень B)
# ============================================================
FILES_ALLOWED_DIRS = (
    "/data/data/com.termux/files/home/personal_ai_brain",
    "/storage/emulated/0/Download",
    "/storage/emulated/0/Documents",
    "/storage/emulated/0/\u043c\u043e\u0434\u0435\u043b\u0438",
)

FILES_MAX_CHARS = 20000

# === SECRETS_DENYLIST (№20): файлы с секретами не читаются/не пишутся никогда.
# Матчится по ПОЛНОМУ пути (realpath) — обход через ~/ или ./ невозможен.
SECRETS_DENY_BASENAMES = (".env", ".pem")
SECRETS_DENY_SUBSTRINGS = ("credential",)
SECRETS_DENY_SUFFIXES = (".key",)


def _is_secret_path(real_path: str) -> bool:
    base = os.path.basename(real_path)
    if base in SECRETS_DENY_BASENAMES or base.startswith(".env"):
        return True
    low = base.lower()
    if any(s in low for s in SECRETS_DENY_SUBSTRINGS):
        return True
    if any(low.endswith(sfx) for sfx in SECRETS_DENY_SUFFIXES):
        return True
    return False


def _files_path_allowed(real_path: str) -> bool:
    """Containment-проверка (аудит #15 PATH_SPOOF) + denylist секретов (№20)."""
    if _is_secret_path(real_path):
        return False
    return any(
        real_path == allowed or real_path.startswith(allowed + os.sep)
        for allowed in FILES_ALLOWED_DIRS
    )


def tool_read_file(path: str, start_line=None, end_line=None) -> dict:
    """Читает файл только из разрешённых директорий (FILES_ALLOWED_DIRS).
    Поддерживает необязательный диапазон строк start_line..end_line (1-based, включительно)."""
    try:
        real_path = os.path.realpath(os.path.expanduser(path))
    except Exception as e:
        return {"ok": False, "result": None, "error": f"BAD_PATH: {e}"}

    if not _files_path_allowed(real_path):
        return {"ok": False, "result": None,
                "error": f"PATH_NOT_ALLOWED: '{real_path}'"}

    if not os.path.isfile(real_path):
        return {"ok": False, "result": None,
                "error": f"NOT_A_FILE: '{real_path}'"}

    # Чтение диапазона строк
    if start_line is not None or end_line is not None:
        try:
            s = int(start_line) if start_line is not None else 1
            e = int(end_line) if end_line is not None else None
            if s < 1:
                s = 1
            if e is not None and e < s:
                return {"ok": False, "result": None,
                        "error": f"INVALID_RANGE: end_line ({e}) < start_line ({s})"}
            with open(real_path, "r", encoding="utf-8", errors="replace") as f:
                lines_out = []
                for i, line in enumerate(f, 1):
                    if i < s:
                        continue
                    if e is not None and i > e:
                        break
                    lines_out.append(line)
            content = "".join(lines_out)
            if not content:
                return {"ok": False, "result": None,
                        "error": f"EMPTY_RANGE: no lines in range {s}-{e}"}
            header = f"[Строки {s}-{e} из файла {os.path.basename(real_path)}]\n"
            return {"ok": True, "result": header + content, "error": None}
        except ValueError as ve:
            return {"ok": False, "result": None, "error": f"INVALID_LINE_PARAM: {ve}"}
        except Exception as ex:
            return {"ok": False, "result": None, "error": f"READ_ERROR: {ex}"}

    # Полное чтение (без диапазона) — прежнее поведение
    try:
        with open(real_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(FILES_MAX_CHARS + 1)
    except Exception as e:
        return {"ok": False, "result": None, "error": f"READ_ERROR: {e}"}

    if len(content) > FILES_MAX_CHARS:
        content = content[:FILES_MAX_CHARS] + "\n... файл обрезан, превышен лимит символов"

    return {"ok": True, "result": content, "error": None}


FILES_MAX_WRITE_CHARS = 20000

def tool_write_file(path: str, content: str) -> dict:
    """Создаёт НОВЫЙ файл в разрешённых директориях. Если файл уже
    существует — отказ (перезапись не поддерживается этим инструментом)."""
    if content is None or len(content) > FILES_MAX_WRITE_CHARS:
        return {"ok": False, "result": None,
                "error": f"CONTENT_TOO_LARGE: max {FILES_MAX_WRITE_CHARS} chars"}

    try:
        real_path = os.path.realpath(os.path.expanduser(path))
    except Exception as e:
        return {"ok": False, "result": None, "error": f"BAD_PATH: {e}"}

    if not _files_path_allowed(real_path):
        return {"ok": False, "result": None,
                "error": f"PATH_NOT_ALLOWED: '{real_path}'"}

    if os.path.exists(real_path):
        return {"ok": False, "result": None,
                "error": f"FILE_ALREADY_EXISTS: '{real_path}' (\u043f\u0435\u0440\u0435\u0437\u0430\u043f\u0438\u0441\u044c \u0437\u0430\u043f\u0440\u0435\u0449\u0435\u043d\u0430 \u044d\u0442\u0438\u043c \u0438\u043d\u0441\u0442\u0440\u0443\u043c\u0435\u043d\u0442\u043e\u043c)"}

    try:
        os.makedirs(os.path.dirname(real_path), exist_ok=True)
        with open(real_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        return {"ok": False, "result": None, "error": f"WRITE_ERROR: {e}"}

    return {"ok": True, "result": f"\u0424\u0430\u0439\u043b \u0441\u043e\u0437\u0434\u0430\u043d: {real_path}", "error": None}


# ============================================================
# [23] TOOL CONTROLLER — FILE SEARCH / EDIT / DIRECTORY
# ============================================================

FILES_MAX_SEARCH_RESULTS = 100
FILES_MAX_EDIT_CHARS = 20000


def tool_web_fetch(url: str, max_chars: int = 15000) -> dict:
    """Получает текстовое содержимое веб-страницы. Безопасность: только http/https, блокировка приватных IP."""
    import re as _re
    from urllib.parse import urlparse

    if not url:
        return {"ok": False, "result": None, "error": "EMPTY_URL"}

    try:
        parsed = urlparse(url)
    except Exception:
        return {"ok": False, "result": None, "error": "INVALID_URL"}

    if parsed.scheme not in ("http", "https"):
        return {"ok": False, "result": None, "error": f"SCHEME_NOT_ALLOWED: '{parsed.scheme}'"}

    hostname = parsed.hostname or ""
    # Блокировка приватных IP и localhost
    private_patterns = [
        r"^localhost$", r"^127\.", r"^10\.", r"^172\.(1[6-9]|2\d|3[01])\.",
        r"^192\.168\.", r"^0\.", r"^::1$", r"^fc", r"^fd", r"^fe80:",
    ]
    for pat in private_patterns:
        if _re.match(pat, hostname, _re.IGNORECASE):
            return {"ok": False, "result": None, "error": f"PRIVATE_HOST_BLOCKED: '{hostname}'"}

    try:
        resp = requests.get(
            url,
            timeout=15,
            headers={"User-Agent": "PersonalAIBrain/4.4 (Termux)"},
            allow_redirects=True,
        )
        resp.raise_for_status()
    except requests.Timeout:
        return {"ok": False, "result": None, "error": "TIMEOUT"}
    except requests.ConnectionError:
        return {"ok": False, "result": None, "error": "CONNECTION_ERROR"}
    except requests.HTTPError as e:
        return {"ok": False, "result": None, "error": f"HTTP_{e.response.status_code}"}
    except Exception as e:
        return {"ok": False, "result": None, "error": f"FETCH_ERROR: {e}"}

    content_type = resp.headers.get("Content-Type", "")
    if "text/html" in content_type:
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
        except ImportError:
            text = _re.sub(r"<[^>]+>", "", resp.text)
    else:
        text = resp.text

    # Нормализация пробелов
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    text = "\n".join(lines)

    if len(text) > max_chars:
        text = text[:max_chars] + "\n... [TRUNCATED]"

    return {"ok": True, "result": text, "error": None}


def tool_directory_list(path: str) -> dict:
    """Показывает содержимое разрешённой директории."""
    try:
        real_path = os.path.realpath(os.path.expanduser(path))
    except Exception as e:
        return {"ok": False, "result": None, "error": f"BAD_PATH: {e}"}

    if not any(
        real_path == allowed or real_path.startswith(allowed + os.sep)
        for allowed in FILES_ALLOWED_DIRS
    ):
        return {
            "ok": False,
            "result": None,
            "error": f"PATH_NOT_ALLOWED: '{real_path}'"
        }

    if not os.path.isdir(real_path):
        return {
            "ok": False,
            "result": None,
            "error": f"NOT_A_DIRECTORY: '{real_path}'"
        }

    try:
        entries = []
        for entry in sorted(os.scandir(real_path), key=lambda e: e.name.lower()):
            prefix = "[DIR] " if entry.is_dir() else "[FILE]"
            entries.append(f"{prefix} {entry.name}")

        if not entries:
            result = "(директория пуста)"
        else:
            result = "\n".join(entries)

        return {"ok": True, "result": result, "error": None}

    except Exception as e:
        return {
            "ok": False,
            "result": None,
            "error": f"DIRECTORY_LIST_ERROR: {e}"
        }


def tool_file_search(query: str, path: str) -> dict:
    """Ищет текст в файле или рекурсивно в разрешённой директории."""
    if not query:
        return {"ok": False, "result": None, "error": "EMPTY_QUERY"}

    try:
        real_path = os.path.realpath(os.path.expanduser(path))
    except Exception as e:
        return {"ok": False, "result": None, "error": f"BAD_PATH: {e}"}

    if not any(
        real_path == allowed or real_path.startswith(allowed + os.sep)
        for allowed in FILES_ALLOWED_DIRS
    ):
        return {
            "ok": False,
            "result": None,
            "error": f"PATH_NOT_ALLOWED: '{real_path}'"
        }

    if not os.path.exists(real_path):
        return {
            "ok": False,
            "result": None,
            "error": f"PATH_NOT_FOUND: '{real_path}'"
        }

    files_to_search = []

    if os.path.isfile(real_path):
        files_to_search.append(real_path)
    elif os.path.isdir(real_path):
        for root, dirs, files in os.walk(real_path):
            dirs[:] = [
                d for d in dirs
                if d not in {".git", "__pycache__", ".venv", "venv", "node_modules", ".backups", "backups_golden", ".diag_tmp"}
            ]
            for name in files:
                files_to_search.append(os.path.join(root, name))

    results = []

    for file_path in files_to_search:
        if len(results) >= FILES_MAX_SEARCH_RESULTS:
            break

        try:
            with open(
                file_path,
                "r",
                encoding="utf-8",
                errors="replace"
            ) as f:
                for line_no, line in enumerate(f, 1):
                    if query.lower() in line.lower():
                        results.append(
                            f"{file_path}:{line_no}: {line.rstrip()}"
                        )

                        if len(results) >= FILES_MAX_SEARCH_RESULTS:
                            break

        except (OSError, UnicodeError):
            continue

    if not results:
        return {
            "ok": True,
            "result": f"Совпадений не найдено: {query}",
            "error": None
        }

    result = "\n".join(results)

    if len(result) > FILES_MAX_CHARS:
        result = (
            result[:FILES_MAX_CHARS]
            + "\n... результаты обрезаны"
        )

    return {
        "ok": True,
        "result": result,
        "error": None
    }


def tool_file_edit(path: str, old_text: str, new_text: str, test: str = None) -> dict:
    """Точечно изменяет существующий файл только при одном совпадении."""
    if not old_text:
        return {
            "ok": False,
            "result": None,
            "error": "EMPTY_OLD_TEXT"
        }

    if len(new_text) > FILES_MAX_EDIT_CHARS:
        return {
            "ok": False,
            "result": None,
            "error": f"NEW_TEXT_TOO_LARGE: max {FILES_MAX_EDIT_CHARS} chars"
        }

    try:
        real_path = os.path.realpath(os.path.expanduser(path))
    except Exception as e:
        return {
            "ok": False,
            "result": None,
            "error": f"BAD_PATH: {e}"
        }

    if not any(
        real_path == allowed or real_path.startswith(allowed + os.sep)
        for allowed in FILES_ALLOWED_DIRS
    ):
        return {
            "ok": False,
            "result": None,
            "error": f"PATH_NOT_ALLOWED: '{real_path}'"
        }

    if not os.path.isfile(real_path):
        return {
            "ok": False,
            "result": None,
            "error": f"NOT_A_FILE: '{real_path}'"
        }

    try:
        with open(
            real_path,
            "r",
            encoding="utf-8",
            errors="replace"
        ) as f:
            content = f.read()
    except Exception as e:
        return {
            "ok": False,
            "result": None,
            "error": f"READ_ERROR: {e}"
        }

    count = content.count(old_text)

    if count != 1:
        return {
            "ok": False,
            "result": None,
            "error": (
                f"EDIT_REQUIRES_EXACTLY_ONE_MATCH: найдено {count}"
            )
        }

    new_content = content.replace(old_text, new_text, 1)

    if len(new_content) > FILES_MAX_EDIT_CHARS * 2:
        return {
            "ok": False,
            "result": None,
            "error": "EDITED_FILE_TOO_LARGE"
        }

    # BACKUP: постоянная копия перед изменением
    try:
        backup_dir = os.path.join(
            os.path.dirname(os.path.realpath(__file__)),
            ".backups"
        )
        os.makedirs(backup_dir, exist_ok=True)

        base_name = os.path.basename(real_path)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(
            backup_dir,
            f"{base_name}.bak_{timestamp}"
        )

        import shutil
        shutil.copy2(real_path, backup_path)
    except Exception as e:
        return {
            "ok": False,
            "result": None,
            "error": f"BACKUP_ERROR: {e}"
        }

    try:
        with open(real_path, "w", encoding="utf-8") as f:
            f.write(new_content)
    except Exception as e:
        return {
            "ok": False,
            "result": None,
            "error": f"WRITE_ERROR: {e}"
        }

    # VERIFIER v2: diff + py_compile + targeted test
    verifier_result = verifier.verify_file_edit(
        real_path,
        content,
        new_content,
        test_name=test,
        test_runner=tool_run_tests
    )

    if verifier_result.get("rollback"):
        return {
            "ok": False,
            "result": None,
            "error": f"VERIFIER_PY_COMPILE_FAILED: {verifier_result.get('errors')}",
            "verifier": verifier_result
        }

    if verifier_result.get("ok") is False:
        return {
            "ok": False,
            "result": None,
            "error": f"VERIFIER_FAILED: {verifier_result.get('errors')}",
            "verifier": verifier_result
        }

    verified_mark = " VERIFIED" if real_path.endswith(".py") else ""
    return {
        "ok": True,
        "result": (
            f"Файл изменён: {real_path}. "
            f"Заменено совпадение: 1{verified_mark}"
        ),
        "error": None,
        "verifier": verifier_result
    }


# ============================================================
# [24] TOOL CONTROLLER — DOCUMENTS (read-only, PDF, DOCX)
# ============================================================

def _check_allowed_path(path: str):
    """\u041e\u0431\u0449\u0430\u044f \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u043f\u0443\u0442\u0438 \u0447\u0435\u0440\u0435\u0437 whitelist. \u0412\u043e\u0437\u0432\u0440\u0430\u0449\u0430\u0435\u0442 (real_path, error) - error is None if OK."""
    try:
        real_path = os.path.realpath(os.path.expanduser(path))
    except Exception as e:
        return None, f"BAD_PATH: {e}"
    if not _files_path_allowed(real_path):
        return None, f"PATH_NOT_ALLOWED: '{real_path}'"
    if not os.path.isfile(real_path):
        return None, f"NOT_A_FILE: '{real_path}'"
    return real_path, None


def tool_read_pdf(path: str) -> dict:
    """\u0418\u0437\u0432\u043b\u0435\u043a\u0430\u0435\u0442 \u0442\u0435\u043a\u0441\u0442 \u0438\u0437 PDF \u0432 \u0440\u0430\u0437\u0440\u0435\u0448\u0451\u043d\u043d\u044b\u0445 \u0434\u0438\u0440\u0435\u043a\u0442\u043e\u0440\u0438\u044f\u0445."""
    real_path, err = _check_allowed_path(path)
    if err:
        return {"ok": False, "result": None, "error": err}
    try:
        from pypdf import PdfReader
        reader = PdfReader(real_path)
        text_parts = []
        for page in reader.pages:
            text_parts.append(page.extract_text() or "")
        content = "\n".join(text_parts).strip()
    except Exception as e:
        return {"ok": False, "result": None, "error": f"PDF_READ_ERROR: {e}"}

    if not content:
        return {"ok": False, "result": None, "error": "NO_TEXT_EXTRACTED (\u0432\u043e\u0437\u043c\u043e\u0436\u043d\u043e \u0441\u043a\u0430\u043d\u0438\u0440\u043e\u0432\u0430\u043d\u043d\u044b\u0439 PDF \u0431\u0435\u0437 \u0442\u0435\u043a\u0441\u0442\u043e\u0432\u043e\u0433\u043e \u0441\u043b\u043e\u044f)"}

    if len(content) > FILES_MAX_CHARS:
        content = content[:FILES_MAX_CHARS] + "\n... \u0442\u0435\u043a\u0441\u0442 \u043e\u0431\u0440\u0435\u0437\u0430\u043d, \u043f\u0440\u0435\u0432\u044b\u0448\u0435\u043d \u043b\u0438\u043c\u0438\u0442 \u0441\u0438\u043c\u0432\u043e\u043b\u043e\u0432"

    return {"ok": True, "result": content, "error": None}


def tool_read_docx(path: str) -> dict:
    """\u0418\u0437\u0432\u043b\u0435\u043a\u0430\u0435\u0442 \u0442\u0435\u043a\u0441\u0442 \u0438\u0437 DOCX \u0432 \u0440\u0430\u0437\u0440\u0435\u0448\u0451\u043d\u043d\u044b\u0445 \u0434\u0438\u0440\u0435\u043a\u0442\u043e\u0440\u0438\u044f\u0445."""
    real_path, err = _check_allowed_path(path)
    if err:
        return {"ok": False, "result": None, "error": err}
    try:
        import docx
        doc = docx.Document(real_path)
        content = "\n".join(p.text for p in doc.paragraphs).strip()
    except Exception as e:
        return {"ok": False, "result": None, "error": f"DOCX_READ_ERROR: {e}"}

    if not content:
        return {"ok": False, "result": None, "error": "NO_TEXT_EXTRACTED"}

    if len(content) > FILES_MAX_CHARS:
        content = content[:FILES_MAX_CHARS] + "\n... \u0442\u0435\u043a\u0441\u0442 \u043e\u0431\u0440\u0435\u0437\u0430\u043d, \u043f\u0440\u0435\u0432\u044b\u0448\u0435\u043d \u043b\u0438\u043c\u0438\u0442 \u0441\u0438\u043c\u0432\u043e\u043b\u043e\u0432"

    return {"ok": True, "result": content, "error": None}
# ============================================================
# ============================================================

if __name__ == "__main__":

    main()
