"""
Planner — модуль планирования и выполнения сложных задач.

Разбивает сложную задачу на шаги, выполняет их последовательно,
анализирует результаты и переходит к следующему шагу.
"""

import re
import json

from verifier import verify_code, format_report, extract_python_blocks
import time
from datetime import datetime


# ============================================================
# ЗАПАСНЫЕ МОДЕЛИ ДЛЯ ПЕРЕКЛЮЧЕНИЯ ПРИ 429
# ============================================================

FALLBACK_MODELS = [
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/nemotron-3.5-lightning:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "google/gemma-4-31b-it:free",
]

# Текущий индекс запасной модели
_current_fallback_index = 0


def get_next_model(current_model: str) -> str:
    """
    Возвращает следующую модель из списка запасных.
    """
    global _current_fallback_index
    
    # Ищем текущую модель в списке
    if current_model in FALLBACK_MODELS:
        idx = FALLBACK_MODELS.index(current_model)
        next_idx = (idx + 1) % len(FALLBACK_MODELS)
        return FALLBACK_MODELS[next_idx]
    
    # Если текущей модели нет в списке, возвращаем первую
    return FALLBACK_MODELS[0]


# ============================================================
# КЛЮЧЕВЫЕ СЛОВА ДЛЯ ОПРЕДЕЛЕНИЯ СЛОЖНЫХ ЗАДАЧ
# ============================================================

COMPLEX_KEYWORDS = {
    # Действия, требующие нескольких шагов
    "создай", "напиши", "разработай", "спроектируй", "построй",
    "сделай", "собери", "реализуй", "настрой", "установи",
    
    # Многоступенчатые задачи
    "бот", "приложение", "сайт", "скрипт", "программ",
    "систем", "сервис", "инструмент", "утилита",
    
    # Задачи с несколькими компонентами
    "полностью", "с нуля", "целиком", "весь", "всю",
    "с документацией", "с тестами", "с инструкцией"
}

# Задачи, которые НЕ требуют планирования
SIMPLE_KEYWORDS = {
    "объясни", "что такое", "как работает", "расскажи",
    "привет", "спасибо", "помоги", "подскажи",
    "сколько", "когда", "где", "кто", "почему"
}


# ============================================================
# ОПРЕДЕЛЕНИЕ СЛОЖНОСТИ ЗАДАЧИ
# ============================================================

def is_complex_task(question: str) -> bool:
    """
    Определяет, требует ли задача декомпозиции на шаги.
    
    Возвращает True для сложных задач, которые нужно планировать.
    """
    if not question or len(question) < 15:
        return False
    
    text = question.lower()
    
    # ПРОСТЫЕ ЗАДАЧИ — не планируем
    simple_patterns = [
        r"напиши .{0,20}(функцию|метод|класс|код|скрипт)",
        r"объясни .{3,}",
        r"что такое .{3,}",
        r"как работает .{3,}",
        r"привет",
    ]
    
    for pattern in simple_patterns:
        if re.search(pattern, text):
            return False
    
    # Проверяем наличие ключевых слов сложных задач
    complex_score = sum(1 for keyword in COMPLEX_KEYWORDS if keyword in text)
    
    # Проверяем наличие простых ключевых слов
    simple_score = sum(1 for keyword in SIMPLE_KEYWORDS if keyword in text)
    
    # Если больше сложных слов и задача достаточно длинная
    if complex_score > simple_score and len(question) > 20:
        return True
    
    # Специальные паттерны для создания проектов
    creation_patterns = [
        r"создай .{5,}",
        r"сделай .{5,}",
        r"разработай .{5,}",
        r"спроектируй .{5,}",
    ]
    
    for pattern in creation_patterns:
        if re.search(pattern, text):
            return True
    
    return False


# ============================================================
# ГЕНЕРАЦИЯ ПЛАНА
# ============================================================

def generate_plan(question: str, ask_model_func, model_id: str) -> list:
    """
    Генерирует план выполнения задачи через модель.

    Устойчивый вариант:
    - делает несколько попыток;
    - умеет извлекать JSON из markdown-блоков;
    - при ошибке возвращает fallback-план.
    """

    def fallback_plan(q: str) -> list:
        """
        Резервный план, если модель не смогла вернуть JSON.
        """
        text = q.lower()

        if "калькулятор" in text:
            return [
                {
                    "step": 1,
                    "action": "Определить функции арифметических операций",
                    "details": "Создать функции add, subtract, multiply, divide с обработкой деления на ноль."
                },
                {
                    "step": 2,
                    "action": "Реализовать ввод и валидацию выражения",
                    "details": "Принимать выражение вида '5 + 3', проверять формат, оператор и числа."
                },
                {
                    "step": 3,
                    "action": "Создать главный цикл программы",
                    "details": "Запрашивать выражения до команды exit или quit, выполнять операции и выводить результат."
                },
                {
                    "step": 4,
                    "action": "Собрать итоговый Python-файл",
                    "details": "Объединить функции, ввод, обработку ошибок и точку входа if __name__ == '__main__'."
                }
            ]

        if "бот" in text:
            return [
                {
                    "step": 1,
                    "action": "Определить архитектуру бота",
                    "details": "Описать зависимости, структуру файлов и основные обработчики."
                },
                {
                    "step": 2,
                    "action": "Реализовать основной код бота",
                    "details": "Создать запуск, обработку команд и базовую логику."
                },
                {
                    "step": 3,
                    "action": "Добавить конфигурацию и инструкции запуска",
                    "details": "Описать переменные окружения, установку зависимостей и команду запуска."
                },
                {
                    "step": 4,
                    "action": "Собрать итоговый проект",
                    "details": "Объединить код и инструкции в рабочий результат."
                }
            ]

        return [
            {
                "step": 1,
                "action": "Проанализировать требования задачи",
                "details": "Определить входные данные, ожидаемый результат и ограничения."
            },
            {
                "step": 2,
                "action": "Реализовать основную логику",
                "details": "Написать основной код или инструкции выполнения."
            },
            {
                "step": 3,
                "action": "Добавить обработку ошибок и проверку",
                "details": "Учесть некорректный ввод, исключения и крайние случаи."
            },
            {
                "step": 4,
                "action": "Собрать итоговый результат",
                "details": "Объединить части в финальный рабочий вариант."
            }
        ]

    def extract_plan_json(response_text: str):
        """
        Извлекает JSON-массив из ответа модели.
        """
        if not response_text:
            return None

        # Сначала пробуем блок ```json ... ```
        json_block = re.search(r"```json\s*(.*?)\s*```", response_text, re.DOTALL | re.IGNORECASE)
        if json_block:
            response_text = json_block.group(1)

        # Затем ищем первый JSON-массив
        start = response_text.find("[")
        end = response_text.rfind("]")

        if start == -1 or end == -1 or end <= start:
            return None

        raw_json = response_text[start:end + 1]

        try:
            plan = json.loads(raw_json)
        except json.JSONDecodeError:
            return None

        if not isinstance(plan, list) or len(plan) < 2:
            return None

        normalized = []

        for i, item in enumerate(plan, 1):
            if not isinstance(item, dict):
                continue

            action = str(item.get("action", "")).strip()
            details = str(item.get("details", "")).strip()

            if not action:
                continue

            normalized.append({
                "step": i,
                "action": action,
                "details": details
            })

        if len(normalized) < 2:
            return None

        return normalized[:5]

    system_prompt = """Ты — планировщик задач.

Верни СТРОГО JSON-массив без пояснений и без markdown.

Формат:
[
  {"step": 1, "action": "краткое действие", "details": "детали выполнения"},
  {"step": 2, "action": "краткое действие", "details": "детали выполнения"}
]

Правила:
- Отвечай только JSON.
- 1-2 шага максимум.
- Если задача простая — один шаг с полным решением.
- Если сложная — два шага: основная логика + интеграция.
- Не добавляй шаги типа "открыть редактор" или "создать файл вручную".
- Каждый шаг должен давать конкретный полезный результат.
- Для задач с кодом шаги должны вести к итоговому рабочему Python-файлу.
"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Разбей задачу на шаги: {question}"}
    ]

    last_error = None

    for attempt in range(2):

        try:
            ok, result = ask_model_func(model_id, messages)

            if ok:
                response_text = result.get("answer", "") or result.get("content", "")
                plan = extract_plan_json(response_text)

                if plan:
                    return plan

                last_error = "JSON-план не найден в ответе модели"

            else:
                last_error = result.get("error", "unknown")

        except Exception as e:
            last_error = str(e)

        time.sleep(1 + attempt)

    # Если модель не смогла создать JSON-план — используем резервный план.
    return fallback_plan(question)

# ============================================================
# ВЫПОЛНЕНИЕ ПЛАНА
# ============================================================

def execute_plan(plan: list, ask_model_func, model_id: str, print_func=print) -> dict:
    """
    Выполняет план пошагово.
    
    Args:
        plan: список шагов из generate_plan()
        ask_model_func: функция для вызова модели
        print_func: функция для вывода (по умолчанию print)
    
    Returns:
        Словарь с результатами выполнения
    """
    
    results = []
    
    print_func()
    print_func("=" * 64)
    print_func("📋 ПЛАН ВЫПОЛНЕНИЯ")
    print_func("=" * 64)
    
    for i, step in enumerate(plan, 1):
        action = step.get("action", "")
        details = step.get("details", "")
        
        print_func()
        print_func(f"Шаг {i}/{len(plan)}: {action}")
        
        if details:
            print_func(f"Детали: {details}")
        
        # Формируем запрос для выполнения шага
        step_prompt = f"""Выполни следующий шаг задачи:

Шаг: {action}
Детали: {details}

Дай конкретный результат выполнения этого шага (код, команды, инструкции)."""
        
        messages = [
            {"role": "system", "content": "Выполни шаг задачи и дай конкретный результат."},
            {"role": "user", "content": step_prompt}
        ]
        
        # Повторные попытки при пустом ответе или ошибке
        step_success = False
        step_result = None
        step_error = None
        current_model = model_id

        for retry_attempt in range(5):

            try:
                ok, result = ask_model_func(current_model, messages)
                
                if ok:
                    step_result = result.get("answer", "")
                    step_success = True
                    break
                    
                else:
                    step_error = result.get("error", "unknown")
                    
            except Exception as e:
                step_error = str(e)

            # При 429 ждём дольше (лимит запросов)
            if "429" in str(step_error):
                pause = 60 + retry_attempt * 15
                print_func(f"  ⏳ Лимит модели, ждём {pause} сек...")
            else:
                pause = 2 + retry_attempt

            time.sleep(pause)

        if step_success:
            results.append({
                "step": i,
                "action": action,
                "result": step_result,
                "success": True
            })
            
            # Выводим результат
            print_func()
            print_func(step_result)
            
        else:
            results.append({
                "step": i,
                "action": action,
                "result": None,
                "success": False,
                "error": step_error
            })
            print_func(f"⚠ Ошибка: {step_error}")
        
        # Пауза между шагами для соблюдения лимитов API
        if i < len(plan):
            time.sleep(3)
    
    print_func()
    print_func("=" * 64)
    print_func("✅ ПЛАН ВЫПОЛНЕН")
    print_func("=" * 64)
    
    # --------------------------------------------------------
    # СБОРКА ИТОГОВОГО КОДА
    # --------------------------------------------------------
    
    successful_count = sum(1 for r in results if r.get("success"))
    
    if successful_count >= 2:
        print_func()
        print_func("🔧 Сборка итогового кода...")
        
        final_code = None
        
        # Повторные попытки для сборки
        for assembly_attempt in range(3):
            if final_code:
                break
                
            try:
                final_code = assemble_plan(results, ask_model_func, model_id, print_func)
            except Exception:
                final_code = None
            
            if not final_code:
                time.sleep(2 + assembly_attempt)
        
        if final_code:
            # ------------------------------------------------
            # VERIFIER: проверка итогового кода
            # ------------------------------------------------
            print_func()
            print_func("🔍 Проверка кода...")
            
            # Извлекаем код из markdown-блоков, если есть
            code_blocks = extract_python_blocks(final_code)
            code_to_verify = code_blocks[0] if code_blocks else final_code
            
            report = verify_code(code_to_verify)
            
            if not report["ok"]:
                # Код невалиден — отправляем на доработку
                print_func()
                print_func("⚠ Код содержит ошибки, отправляю на доработку...")
                
                error_details = "; ".join(report.get("errors", []))
                
                fix_prompt = f"""Этот Python-код содержит ошибки:

{error_details}

Исходный код:
```python
{code_to_verify}
```

Исправь все ошибки и выведи только исправленный код в блоке ```python ... ``` без пояснений."""
                
                fix_messages = [
                    {"role": "system", "content": "Исправь ошибки в Python-коде. Выведи только код."},
                    {"role": "user", "content": fix_prompt}
                ]
                
                # Одна попытка доработки
                try:
                    ok, fix_result = ask_model_func(model_id, fix_messages)
                    
                    if ok:
                        fixed_answer = fix_result.get("answer", "")
                        fixed_blocks = extract_python_blocks(fixed_answer)
                        
                        if fixed_blocks:
                            fixed_code = fixed_blocks[0]
                            fixed_report = verify_code(fixed_code)
                            
                            if fixed_report["ok"]:
                                final_code = fixed_code
                                report = fixed_report
                                print_func("✅ Код исправлен успешно")
                            else:
                                print_func("⚠ Исправленный код всё ещё содержит ошибки")
                        else:
                            print_func("⚠ Не удалось извлечь исправленный код")
                    
                except Exception as e:
                    print_func(f"⚠ Ошибка при доработке: {e}")
            
            # Выводим отчёт
            print_func()
            print_func(format_report(report))
            
            # Выводим итоговый код
            print_func()
            print_func("=" * 64)
            print_func("📦 ИТОГОВЫЙ КОД")
            print_func("=" * 64)
            print_func()
            print_func(final_code)
        else:
            print_func()
            print_func("⚠ Не удалось собрать итоговый код")
    
    return {
        "plan": plan,
        "results": results,
        "total_steps": len(plan),
        "successful_steps": successful_count
    }


# ============================================================
# СБОРКА ИТОГОВОГО РЕЗУЛЬТАТА
# ============================================================

def assemble_plan(results: list, ask_model_func, model_id: str, print_func=print) -> str:
    """
    Собирает все успешные результаты шагов в один итоговый код.
    """
    
    successful_results = [r for r in results if r.get("success") and r.get("result")]
    
    if not successful_results:
        return ""
    
    # Извлекаем ТОЛЬКО код из каждого шага
    code_blocks = []
    for r in successful_results:
        result_text = r["result"]
        
        # Ищем блоки кода между ```python и ```
        code_pattern = r"```python\s*(.*?)\s*```"
        matches = re.findall(code_pattern, result_text, re.DOTALL)
        
        if matches:
            code_blocks.append(matches[0].strip())
        else:
            code_blocks.append(result_text.strip())
    
    combined_code = "\n\n\n".join(code_blocks)
    
    assembly_prompt = f"""Вот фрагменты кода из разных шагов задачи:

{combined_code}

Твоя задача — создать ОДИН чистый и минимальный Python-файл.

Правила:
1. Выбери ОДНУ лучшую реализацию из предложенных фрагментов
2. Удали ВСЕ дублирующиеся функции и альтернативные реализации
3. Оставь только то, что нужно для решения исходной задачи
4. Не добавляй лишние функции, которые не запрашивались
5. Убедись, что все функции определены до использования
6. Добавь точку входа if __name__ == "__main__"

Выведи ТОЛЬКО итоговый код в блоке ```python ... ``` без пояснений."""

    messages = [
        {"role": "system", "content": "Объедини Python-код. Выведи только код в ```python```."},
        {"role": "user", "content": assembly_prompt}
    ]
    
    try:
        ok, result = ask_model_func(model_id, messages)
        
        if not ok:
            return ""
        
        answer = result.get("answer", "")
        
        # Извлекаем код из ответа
        code_pattern = r"```python\s*(.*?)\s*```"
        match = re.search(code_pattern, answer, re.DOTALL)
        
        if match:
            return match.group(1).strip()
        
        return answer
        
    except Exception:
        return ""


# ============================================================
# ГЛАВНАЯ ФУНКЦИЯ ПЛАНИРОВЩИКА
# ============================================================

def try_plan_task(question: str, ask_model_func, model_id: str, print_func=print) -> bool:
    """
    Пытается выполнить задачу через Planner.
    
    Returns:
        True если задача была спланирована и выполнена,
        False если задача простая и Planner не нужен
    """
    
    if not is_complex_task(question):
        return False
    
    print_func()
    print_func("🧠 Анализ задачи...")
    
    plan = generate_plan(question, ask_model_func, model_id)
    
    if not plan:
        print_func("⚠ Не удалось создать план, выполняю как обычную задачу")
        return False
    
    execute_plan(plan, ask_model_func, model_id, print_func)
    
    return True
