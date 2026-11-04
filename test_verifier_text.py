"""
Детерминированные тесты verify_text_response.
Проверяют 5 категорий: empty, malformed, incomplete, suspicious, valid.
Включают отрицательные проверки: технический термин в обычном тексте не считается malformed/suspicious.
"""

import importlib.util
import sys

FILE = "verifier.py"
spec = importlib.util.spec_from_file_location("verifier", FILE)
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)

results = {}


def check(label, condition, detail=""):
    if condition:
        print(f"  \u2705 {label}")
        return True
    else:
        print(f"  \u274c {label} {detail}")
        return False


def cat(text):
    return verifier.verify_text_response(text)["category"]


print("=" * 64)
print("TEST verify_text_response")
print("=" * 64)

# --- EMPTY ---
print("\n[1] empty")
ok = True
ok &= check("empty string", cat("") == "empty")
ok &= check("whitespace", cat("   \n\t  ") == "empty")
ok &= check("None", cat(None) == "empty")
ok &= check("empty -> ok=False", verifier.verify_text_response("")["ok"] is False)
results["empty"] = ok

# --- MALFORMED ---
print("\n[2] malformed")
ok = True
ok &= check("traceback — ответ начинается с Traceback",
            cat("Traceback (most recent call last): ...") == "malformed")
ok &= check("HTTP_500 — весь ответ", cat("HTTP_500") == "malformed")
ok &= check("HTTP_429 — весь ответ", cat("HTTP_429") == "malformed")
ok &= check("HTTP_504 — весь ответ", cat("HTTP_504") == "malformed")
ok &= check("HTTP_500 с точкой — весь ответ", cat("HTTP_500.") == "malformed")
ok &= check("LOCAL_HTTP_503 — весь ответ", cat("LOCAL_HTTP_503") == "malformed")
ok &= check("LOCAL_HTTP_503 с точкой", cat("LOCAL_HTTP_503.") == "malformed")
ok &= check("LOCAL_SERVICE_UNAVAILABLE — весь ответ",
            cat("LOCAL_SERVICE_UNAVAILABLE") == "malformed")
ok &= check("<error> — ответ начинается с тега",
            cat("<error> something bad</error>") == "malformed")
ok &= check("ALL_MODELS_IN_COOLDOWN — весь ответ",
            cat("ALL_MODELS_IN_COOLDOWN") == "malformed")
ok &= check("NO_MODEL_SELECTED — весь ответ",
            cat("NO_MODEL_SELECTED") == "malformed")
ok &= check("malformed -> ok=False",
            verifier.verify_text_response("HTTP_500")["ok"] is False)
results["malformed"] = ok

# --- INCOMPLETE ---
print("\n[3] incomplete")
ok = True
ok &= check("unclosed code fence",
            cat("```python\nprint(1)") == "incomplete")
ok &= check("truncation marker <truncated>",
            cat("Начало ответа… <truncated>") == "incomplete")
ok &= check("truncation marker [cut]",
            cat("Текст [cut]") == "incomplete")
ok &= check("incomplete -> ok=False",
            verifier.verify_text_response("```python\nx=1")["ok"] is False)

ok &= check("обычная фраза с многоточием — valid",
            cat("Хорошо, подумаю…") == "valid")
ok &= check("обычная фраза, заканчивается на 'и' — valid",
            cat("Я пошёл в магазин и") == "valid")
ok &= check("обычная фраза без точки — valid",
            cat("Это ответ без точки") == "valid")
ok &= check("закрытый code fence — valid",
            cat("```python\nprint(1)\n```") == "valid")
ok &= check("JSON-подобный текст без парсинга — valid",
            cat('{"key": "value"') == "valid")
results["incomplete"] = ok

# --- SUSPICIOUS ---
print("\n[4] suspicious")
ok = True
ok &= check("TOOL BRIDGE + итерация",
            cat("🔧 TOOL BRIDGE | итерация 1/5") == "suspicious")
ok &= check("Context Manager",
            cat("📐 Context Manager [API]: 100→50") == "suspicious")
ok &= check("lock_type = (присвоение)",
            cat("lock_type = MANUAL") == "suspicious")
ok &= check("model_lock = (присвоение)",
            cat("model_lock = qwen3") == "suspicious")
ok &= check("cooldown_until = (присвоение)",
            cat("cooldown_until = 1234567890") == "suspicious")
ok &= check("empty_streak = (присвоение)",
            cat("empty_streak = 2") == "suspicious")
ok &= check("rate_429 = (присвоение)",
            cat("rate_429 = 5") == "suspicious")
ok &= check("EMPTY_STREAK_COOLDOWN — весь ответ",
            cat("EMPTY_STREAK_COOLDOWN") == "suspicious")
ok &= check("suspicious -> ok=False",
            verifier.verify_text_response("lock_type = MANUAL")["ok"] is False)
results["suspicious"] = ok

# --- VALID ---
print("\n[5] valid")
ok = True
ok &= check("простое приветствие",
            cat("Привет! Как я могу помочь?") == "valid")
ok &= check("ответ с точкой",
            cat("Хорошо, я понял задачу.") == "valid")
ok &= check("ответ без точки",
            cat("Это ответ без точки") == "valid")
ok &= check("ответ с многоточием",
            cat("Хорошо, подумаю…") == "valid")
ok &= check("markdown с закрытым кодом",
            cat("```python\nx=1\n```\nГотово.") == "valid")
ok &= check("valid -> ok=True",
            verifier.verify_text_response("Привет!")["ok"] is True)
results["valid"] = ok

# --- ОТРИЦАТЕЛЬНЫЕ ПРОВЕРКИ ---
print("\n[5-отриц] valid — технический термин в обычном тексте")
ok = True
ok &= check("HTTP_500 как упоминание в объяснении — valid",
            cat("В прошлый раз ошибка была HTTP_500, но я её исправил.") == "valid")
ok &= check("HTTP_504 как упоминание — valid",
            cat("HTTP_504 означает, что сервер не ответил вовремя.") == "valid")
ok &= check("LOCAL_HTTP_503 как упоминание — valid",
            cat("При прошлом сбое появился LOCAL_HTTP_503, это значит сервер вернул 503.") == "valid")
ok &= check("NO_MODEL_SELECTED как упоминание — valid",
            cat("Внутренний код NO_MODEL_SELECTED означает, что модель не выбрана.") == "valid")
ok &= check("Traceback как упоминание — valid",
            cat("При запуске возник Traceback, но я его починил.") == "valid")
ok &= check("LOCAL_SERVICE_UNAVAILABLE как упоминание — valid",
            cat("LOCAL_SERVICE_UNAVAILABLE — это код ошибки, который возвращает Brain.") == "valid")
ok &= check("lock_type без присвоения — valid",
            cat("Поле lock_type принимает значения AUTO или MANUAL.") == "valid")
ok &= check("model_lock без присвоения — valid",
            cat("Внутри Brain используется model_lock для фиксации модели.") == "valid")
ok &= check("cooldown_until без присвоения — valid",
            cat("Поле cooldown_until хранит время окончания кулдауна.") == "valid")
ok &= check("empty_streak без присвоения — valid",
            cat("empty_streak считает пустые ответы подряд.") == "valid")
results["valid_negative"] = ok

# --- ИТОГ ---
print("\n" + "=" * 64)
print("ИТОГ")
print("=" * 64)
for k in ["empty", "malformed", "incomplete", "suspicious", "valid", "valid_negative"]:
    mark = "\u2705" if results.get(k) else "\u274c"
    print(f"{mark} {k}")
print("=" * 64)

all_ok = all(results.values())
if all_ok:
    print("\U0001F389 ВСЕ ТЕСТЫ verify_text_response ПРОШЛИ")
    sys.exit(0)
else:
    print("\u26a0\ufe0f ЕСТЬ ПРОБЛЕМЫ")
    sys.exit(1)
