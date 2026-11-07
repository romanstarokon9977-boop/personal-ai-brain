#!/usr/bin/env python3
"""Read-only synthetic benchmark for the local llama.cpp embedding endpoint.

No project files or memory are read or written. All benchmark data is in memory.
"""
import argparse
import json
import math
import os
import resource
import statistics
import time
import urllib.error
import urllib.request

PAIRS = [
    # True paraphrases
    ("paraphrase", True, "Роман живёт в Германии.", "Роман проживает на территории Германии."),
    ("paraphrase", True, "Для запуска Brain используется Termux.", "Brain запускается через приложение Termux."),
    ("paraphrase", True, "Основная цель проекта — создать персонального ИИ-помощника.", "Проект направлен на разработку личного интеллектуального ассистента."),
    ("paraphrase", True, "Пользователь предпочитает короткие и точные ответы.", "Пользователю нравятся лаконичные ответы по существу."),
    ("paraphrase", True, "Резервная копия создаётся перед изменением данных.", "До внесения изменений сначала сохраняется backup данных."),
    # Structural semantic duplicates
    ("semantic_duplicate", True, "После перезагрузки телефона локальный сервер снова доступен.", "Локальный сервер восстанавливает доступность при новом запуске устройства."),
    ("semantic_duplicate", True, "Все изменения сначала проверяются на отдельной ветке.", "Для предварительной проверки изменений применяется изолированная Git-ветка."),
    ("semantic_duplicate", True, "Внешний API не должен получать содержимое личной памяти.", "Данные персональной памяти запрещено передавать стороннему API."),
    ("semantic_duplicate", True, "Перед сохранением система проверяет целостность JSON.", "JSON проходит проверку корректности до записи на диск."),
    ("semantic_duplicate", True, "Модель возвращает вектор размерности 384.", "Размерность embedding-вектора, полученного от модели, равна 384."),
    # Contradictions
    ("contradiction", False, "Локальный embedding-сервер работает на порту 8090.", "Локальный embedding-сервер работает на порту 8085."),
    ("contradiction", False, "Резервное копирование выполняется ежедневно.", "Резервное копирование выполняется только раз в месяц."),
    ("contradiction", False, "Доступ к файлам разрешён только для чтения.", "Доступ к файлам разрешает их редактирование и удаление."),
    ("contradiction", False, "Основная модель запускается локально на телефоне.", "Основная модель запускается исключительно на удалённом сервере."),
    ("contradiction", False, "Ветка разработки основана на актуальном main.", "Ветка разработки основана на устаревшем релизном коммите."),
    # Negation / presence / absence
    ("negation", False, "Brain подключён к локальному embedding-провайдеру.", "Brain не подключён к локальному embedding-провайдеру."),
    ("negation", False, "Пользователь разрешил чтение документов.", "Пользователь не разрешал чтение документов."),
    ("negation", False, "На устройстве включён VPN.", "На устройстве VPN выключен."),
    ("negation", False, "В памяти сохранён адрес проекта.", "В памяти адрес проекта не сохранён."),
    ("negation", False, "Автоматическое слияние изменений разрешено.", "Автоматическое слияние изменений запрещено."),
    # Different numbers and dates
    ("numbers_dates", False, "На телефоне установлено 12 ГБ оперативной памяти.", "На телефоне установлено 8 ГБ оперативной памяти."),
    ("numbers_dates", False, "Проверка завершилась 7 ноября 2026 года.", "Проверка завершилась 8 ноября 2026 года."),
    ("numbers_dates", False, "Порог cosine similarity установлен на уровне 0.82.", "Порог cosine similarity установлен на уровне 0.92."),
    ("numbers_dates", False, "Резервная копия содержит 37 записей памяти.", "Резервная копия содержит 73 записи памяти."),
    ("numbers_dates", False, "Сервер использует порт 8090.", "Сервер использует порт 8089."),
    # Causally related but independent facts
    ("causal_independent", False, "После обновления Android телефон перезагрузился.", "После перезагрузки Android некоторые приложения запрашивают повторный вход."),
    ("causal_independent", False, "Высокая температура процессора может снижать частоту.", "Снижение частоты процессора увеличивает время выполнения вычислений."),
    ("causal_independent", False, "Потеря интернет-соединения прерывает загрузку модели.", "После загрузки модели её локальный запуск может работать без интернета."),
    ("causal_independent", False, "Ошибка записи может возникнуть из-за нехватки свободного места.", "Освобождение места на диске позволяет создать новую резервную копию."),
    ("causal_independent", False, "Изменение конфигурации может потребовать перезапуска сервера.", "После перезапуска сервер перечитывает сохранённую конфигурацию."),
    # Topically related but distinct facts
    ("topically_related", False, "В GitHub создана ветка для тестирования embedding.", "В GitHub настроена защита основной ветки от прямой записи."),
    ("topically_related", False, "Termux предоставляет Linux-подобную среду на Android.", "В Termux установлен Python версии 3.11."),
    ("topically_related", False, "Семантический поиск сравнивает смысл текстов.", "Консолидация памяти объединяет подтверждённые повторяющиеся записи."),
    ("topically_related", False, "Резервная копия защищает данные от потери.", "Контрольная сумма помогает обнаружить повреждение файла."),
    ("topically_related", False, "Embedding-модель преобразует текст в числовой вектор.", "Cosine similarity измеряет угол между двумя векторами."),
    # Unrelated
    ("unrelated", False, "На кухне закипела вода в электрическом чайнике.", "Осенние листья покрыли тропинку в городском парке."),
    ("unrelated", False, "Музыкант настроил акустическую гитару перед концертом.", "Самолёт набирает высоту после взлёта из аэропорта."),
    ("unrelated", False, "Врач изучил результаты лабораторного анализа крови.", "Пекарь замесил тесто для свежего хлеба."),
    ("unrelated", False, "Космический телескоп наблюдает далёкую галактику.", "Садовник пересадил розовый куст в большой горшок."),
    ("unrelated", False, "Рыбаки вернулись на берег ранним утром.", "Программист исправил ошибку в алгоритме сортировки."),
]

def cosine(a, b):
    if len(a) != len(b) or not a:
        raise ValueError("VECTOR_DIMENSION_MISMATCH")
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if not na or not nb:
        raise ValueError("ZERO_NORM_VECTOR")
    return dot / (na * nb)

def embed(url, model, texts, timeout):
    payload = json.dumps({"model": model, "input": texts}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status = response.status
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"EMBEDDING_REQUEST_FAILED: {exc}") from exc
    elapsed = time.perf_counter() - started
    if status != 200:
        raise RuntimeError(f"HTTP_STATUS_{status}")
    rows = body.get("data")
    if not isinstance(rows, list) or len(rows) != len(texts):
        raise RuntimeError("EMBEDDING_COUNT_MISMATCH")
    rows = sorted(rows, key=lambda item: item.get("index", 0))
    vectors = [item.get("embedding") for item in rows]
    if any(not isinstance(v, list) or not v for v in vectors):
        raise RuntimeError("INVALID_EMBEDDING_VECTOR")
    dim = len(vectors[0])
    if any(len(v) != dim for v in vectors):
        raise RuntimeError("EMBEDDING_DIMENSION_MISMATCH")
    if any(not math.isfinite(float(x)) for v in vectors for x in v):
        raise RuntimeError("NON_FINITE_EMBEDDING_VALUE")
    return vectors, elapsed

def device_snapshot():
    result = {}
    try:
        with open("/proc/meminfo", encoding="ascii") as f:
            info = dict(line.split(":", 1) for line in f if ":" in line)
        result["mem_available_mb"] = round(int(info["MemAvailable"].split()[0]) / 1024, 1)
    except Exception:
        result["mem_available_mb"] = None
    try:
        result["peak_rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    except Exception:
        result["peak_rss_mb"] = None
    temps = []
    for root in ("/sys/class/thermal", "/sys/devices/virtual/thermal"):
        try:
            for name in os.listdir(root):
                path = os.path.join(root, name, "temp")
                if os.path.isfile(path):
                    try:
                        value = float(open(path, encoding="ascii").read().strip())
                        if value > 1000:
                            value /= 1000
                        if -20 <= value <= 150:
                            temps.append(value)
                    except Exception:
                        pass
        except Exception:
            pass
    result["thermal_c_min"] = round(min(temps), 1) if temps else None
    result["thermal_c_max"] = round(max(temps), 1) if temps else None
    return result

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8090/v1/embeddings")
    parser.add_argument("--model", default="multilingual-e5-small")
    parser.add_argument("--threshold", type=float, default=0.82)
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()

    texts = [text for _, _, left, right in PAIRS for text in (left, right)]
    before = device_snapshot()
    vectors1, elapsed1 = embed(args.url, args.model, texts, args.timeout)
    vectors2, elapsed2 = embed(args.url, args.model, texts, args.timeout)
    after = device_snapshot()

    similarities = []
    stability = []
    norms = []
    for i, (_, expected_match, _, _) in enumerate(PAIRS):
        left, right = vectors1[2*i], vectors1[2*i+1]
        score = cosine(left, right)
        predicted = score >= args.threshold
        similarities.append((score, expected_match, predicted))
        stability.extend(cosine(vectors1[j], vectors2[j]) for j in (2*i, 2*i+1))
        norms.extend(math.sqrt(sum(x*x for x in v)) for v in (left, right))

    tp = sum(1 for _, exp, pred in similarities if exp and pred)
    fp = sum(1 for _, exp, pred in similarities if not exp and pred)
    fn = sum(1 for _, exp, pred in similarities if exp and not pred)
    tn = sum(1 for _, exp, pred in similarities if not exp and not pred)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2*precision*recall/(precision+recall) if precision+recall else 0.0

    print("=== P3.2.3 LOCAL EMBEDDING BENCHMARK ===")
    print(f"Endpoint: {args.url}")
    print(f"Pairs: {len(PAIRS)} | texts/request: {len(texts)} | dimensions: {len(vectors1[0])}")
    print(f"Threshold: {args.threshold:.4f}")
    print(f"Request 1: {elapsed1:.3f}s ({elapsed1/len(texts):.4f}s/text)")
    print(f"Request 2: {elapsed2:.3f}s ({elapsed2/len(texts):.4f}s/text)")
    print(f"Vector stability cosine: min={min(stability):.6f} mean={statistics.mean(stability):.6f}")
    print(f"L2 norms: min={min(norms):.6f} max={max(norms):.6f}")
    print(f"Confusion matrix: TP={tp} FP={fp} FN={fn} TN={tn}")
    print(f"Precision={precision:.4f} Recall={recall:.4f} F1={f1:.4f}")
    print("\n--- Per-category results ---")
    for category in dict.fromkeys(item[0] for item in PAIRS):
        group = [(s, e, p) for (s, e, p), pair in zip(similarities, PAIRS) if pair[0] == category]
        errors = sum(1 for _, expected, predicted in group if expected != predicted)
        print(f"{category}: n={len(group)} errors={errors} mean_cosine={statistics.mean(x[0] for x in group):.6f}")
    print("\n--- Pair scores ---")
    for (category, expected, left, right), (score, _, predicted) in zip(PAIRS, similarities):
        mark = "OK" if expected == predicted else "ERROR"
        print(f"{mark:5s} {category:20s} expected={'MATCH' if expected else 'SEPARATE':8s} predicted={'MATCH' if predicted else 'SEPARATE':8s} cosine={score:.6f}")
    print("\n--- Device snapshot (best effort; thermal access may be restricted) ---")
    print(json.dumps({"before": before, "after": after}, ensure_ascii=False, indent=2))
    print("\nNOTE: benchmark is synthetic and read-only; no memory/project files are accessed or modified.")

if __name__ == "__main__":
    main()
