"""Read-only аудит Memory Recall: фактический pipeline, без записи в память."""
import sys, json
sys.path.insert(0, ".")
from memory.memory_core import get_relevant_memory, _load_raw

print("=== 1. СОСТОЯНИЕ ПАМЯТИ (read-only) ===")
data = _load_raw()
entries = data.get("entries", [])
print(f"entries: {len(entries)} | version: {data.get('version')}")
roman_entries = [e for e in entries if "Роман" in e.get("text", "") or "Роман" in e.get("text", "")]
for e in roman_entries:
    print(f"  id={e.get('id','')[:8]}... | cat={e.get('category')} | imp={e.get('importance')} | text: {e.get('text','')[:100]}")

print("\n=== 2. РАЗНЫЕ ФОРМУЛИРОВКИ ВОПРОСА → get_relevant_memory ===")
questions = [
    "как меня зовут?",
    "Кто я?",
    "скажи моё имя",
    "привет",              # контроль: без слов про имя
    "что ты умеешь?",      # контроль: нейтральный
]
for q in questions:
    ctx = get_relevant_memory(q)
    hit = "Роман" in ctx
    relevant_lines = [l for l in ctx.split("\n") if "Роман" in l]
    print(f"\nQ: {q!r} → hit={hit}")
    for line in relevant_lines:
        print(f"   ↳ {line[:120]}")

print("\n=== 3. ГРАНИЦЫ: скоринг конкретных записей ===")
# показать, как score выглядит для罗马-записей при вопросе «как меня зовут»:
qw = "как меня зовут".lower().split()
for e in roman_entries:
    text = e.get("text", "").lower().replace("ё", "е")
    import re
    entry_words = set(re.findall(r"[а-яa-z0-9+#]+", text))
    score = 0
    for w in qw:
        if w in entry_words: score += 2
    print(f"  {e.get('text','')[:60]!r} → score={score}")
print("AUDIT_COMPLETE")
