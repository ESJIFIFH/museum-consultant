"""
ingest.py

Подготовка и индексация корпуса Пушкинского музея
из masterpieces.json для P2.
"""

import hashlib
import html
import json
import re
from collections import Counter
from pathlib import Path

import config


BASE_DIR = Path(__file__).parent
RAW_DIR = config.RAW_DIR
JSON_FILE = RAW_DIR / "masterpieces.json"


# Ключевые слова для определения категории.
CATEGORY_KEYWORDS = {
    "collection": [
        "инвентарный номер",
        "коллекционер",
        "происхождение",
        "год поступления",
        "поступление",
        "коллекция",
    ],
    "object": [
        "название",
        "тип",
        "страна",
        "описание",
        "аннотация",
        "размер",
    ],
    "period": [
        "период",
        "дата создания",
        "год создания",
        "эпоха",
        "династия",
        "век",
    ],
    "attribution": [
        "автор",
        "авторы",
        "материал",
        "техника",
        "место создания",
    ],
}


def value_to_text(value):
    """Преобразует вложенные значения JSON в обычный текст."""

    if value is None:
        return ""

    if isinstance(value, str):
        return value.strip()

    if isinstance(value, (int, float, bool)):
        return str(value)

    if isinstance(value, list):
        parts = []

        for item in value:
            text = value_to_text(item)

            if text:
                parts.append(text)

        return "; ".join(parts)

    if isinstance(value, dict):
        # Для объектов вида {"ru": "...", "en": "..."}
        ru_value = value.get("ru")

        if isinstance(ru_value, str) and ru_value.strip():
            return ru_value.strip()

        parts = []

        for key, item in value.items():
            text = value_to_text(item)

            if text:
                parts.append(f"{key}: {text}")

        return "; ".join(parts)

    return str(value)


def ru_value(record, field):
    """Получает русское значение поля."""

    value = record.get(field, "")

    if isinstance(value, dict):
        return value_to_text(value.get("ru", ""))

    return value_to_text(value)


def read_json(path):
    """
    Читает masterpieces.json.

    Реальная структура файла:

    {
        "3687": {...},
        "3675": {...},
        "3706": {...}
    }

    Поэтому ключ объекта сохраняем как record_id.
    """

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    # Основной случай: словарь ID -> объект
    if isinstance(data, dict):
        if data and all(isinstance(value, dict) for value in data.values()):
            return [
                (str(record_id), record)
                for record_id, record in data.items()
            ]

        # На случай другой структуры JSON
        for key in (
            "data",
            "items",
            "objects",
            "masterpieces",
            "results",
        ):
            value = data.get(key)

            if isinstance(value, list):
                return [
                    (str(index + 1), record)
                    for index, record in enumerate(value)
                    if isinstance(record, dict)
                ]

        return [("1", data)]

    # Если JSON оказался списком
    if isinstance(data, list):
        return [
            (str(index + 1), record)
            for index, record in enumerate(data)
            if isinstance(record, dict)
        ]

    raise ValueError("Неизвестная структура masterpieces.json")


def record_to_text(record_id, record):
    """Превращает один музейный объект в поисковый текст."""

    period_name = ru_value(record.get("period", {}), "name") \
        if isinstance(record.get("period"), dict) else ""

    period_text = ru_value(record.get("period", {}), "text") \
        if isinstance(record.get("period"), dict) else ""

    if period_name and period_text:
        period = f"{period_name} — {period_text}"
    else:
        period = period_name or period_text

    fields = [
        ("ID объекта", record_id),
        ("Название", ru_value(record, "name")),
        ("Инвентарный номер", record.get("inv_num", "")),
        ("Тип", ru_value(record, "type")),
        ("Страна", ru_value(record, "country")),
        ("Период", period),
        ("Год создания", record.get("year", "")),
        ("Год поступления", record.get("get_year", "")),
        ("Место создания", ru_value(record, "producein")),
        ("Происхождение", ru_value(record, "from")),
        ("Материал", ru_value(record, "material")),
        ("Размер", ru_value(record, "size")),
        ("Авторы", value_to_text(record.get("authors"))),
        ("Коллекционеры", value_to_text(record.get("collectors"))),
        ("Описание", ru_value(record, "text")),
        ("Аннотация", ru_value(record, "annotation")),
    ]

    lines = []

    for label, value in fields:
        value = value_to_text(value)

        if value:
            lines.append(f"{label}: {value}")

    return "\n".join(lines)


def clean_text(text):
    """Детерминированная очистка текста."""

    # HTML-сущности: &ndash; -> –, &laquo; -> « и т.д.
    text = html.unescape(text)

    # Переносы внутри слов
    text = re.sub(r"-\s*\n\s*", "", text)

    # Переводы строк заменяем пробелами
    text = text.replace("\r", " ")
    text = text.replace("\n", " ")

    # Повторяющиеся пробелы
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def chunk_text(text, chunk_size, overlap):
    """Фиксированное чанкирование с перекрытием."""

    if chunk_size <= 0:
        raise ValueError("CHUNK_SIZE должен быть больше 0")

    if overlap < 0:
        raise ValueError("CHUNK_OVERLAP не может быть отрицательным")

    if overlap >= chunk_size:
        raise ValueError(
            "CHUNK_OVERLAP должен быть меньше CHUNK_SIZE"
        )

    if not text:
        return []

    step = chunk_size - overlap

    chunks = []

    for start in range(0, len(text), step):
        chunk = text[start:start + chunk_size]

        if chunk:
            chunks.append(chunk)

        if start + chunk_size >= len(text):
            break

    return chunks


def detect_category(text):
    """Определяет одну из категорий P1."""

    text_lower = text.lower()

    scores = {}

    for category, keywords in CATEGORY_KEYWORDS.items():
        score = 0

        for keyword in keywords:
            if keyword in text_lower:
                score += 1

        scores[category] = score

    best_category = max(scores, key=scores.get)

    # Обязательная категория по умолчанию
    if scores[best_category] == 0:
        return "object"

    return best_category


def make_chunk_id(source, record_id, chunk_number, chunk):
    """Создаёт стабильный ID чанка."""

    raw = (
        f"{source}:"
        f"{record_id}:"
        f"{chunk_number}:"
        f"{chunk}"
    )

    return hashlib.sha1(
        raw.encode("utf-8")
    ).hexdigest()


def ingest():
    """Пересобирает ChromaDB из masterpieces.json."""

    if not JSON_FILE.exists():
        raise FileNotFoundError(
            f"Файл не найден: {JSON_FILE}"
        )

    records = read_json(JSON_FILE)

    print(
        f"Найдено записей в masterpieces.json: "
        f"{len(records)}"
    )

    # Полностью пересобираем коллекцию
    config.reset_collection()
    collection = config.get_collection()

    all_ids = []
    all_documents = []
    all_metadatas = []

    total_chunks = 0

    for record_id, record in records:

        raw_text = record_to_text(
            record_id,
            record
        )

        cleaned_text = clean_text(raw_text)

        chunks = chunk_text(
            cleaned_text,
            config.CHUNK_SIZE,
            config.CHUNK_OVERLAP,
        )

        for chunk_number, chunk in enumerate(chunks):

            chunk_id = make_chunk_id(
                JSON_FILE.name,
                record_id,
                chunk_number,
                chunk,
            )

            category = detect_category(chunk)

            all_ids.append(chunk_id)
            all_documents.append(chunk)

            all_metadatas.append(
                {
                    "source": JSON_FILE.name,
                    "page": 0,
                    "category": category,
                    "record_id": record_id,
                }
            )

            total_chunks += 1

    if all_documents:
        collection.add(
            ids=all_ids,
            documents=all_documents,
            metadatas=all_metadatas,
        )

    print("Индекс пересобран заново.")
    print(
        f"Проиндексировано чанков: {total_chunks}"
    )
    print(
        f"Всего в коллекции: {collection.count()}"
    )

    show_category_statistics(collection)


def show_category_statistics(collection):
    """Показывает распределение категорий."""

    result = collection.get(
        include=["metadatas"]
    )

    categories = Counter()

    for metadata in result["metadatas"]:
        category = metadata.get(
            "category",
            "object"
        )

        categories[category] += 1

    print("Распределение категорий:")

    for category, count in sorted(categories.items()):
        print(f"  {category}: {count}")


def evaluate_retrieval():
    """Проверяет retrieval по gold_dataset.json."""

    gold_path = BASE_DIR / "gold_dataset.json"

    if not gold_path.exists():
        print(
            "\nGold dataset пока отсутствует:"
            f" {gold_path}"
        )
        return

    with gold_path.open(
        "r",
        encoding="utf-8"
    ) as f:
        cases = json.load(f)

    # Проверяем, не остался ли шаблон П2
    placeholder_cases = [
        case
        for case in cases
        if "ЗАМЕНИТЕ" in case.get("question", "")
    ]

    if placeholder_cases:
        print(
            "\nGold dataset пока содержит "
            "шаблонные вопросы."
        )
        print(
            "Сначала заменим их на реальные "
            "вопросы по masterpieces.json."
        )
        return

    collection = config.get_collection()

    if collection.count() == 0:
        print("\nКоллекция пуста.")
        return

    evaluated = 0
    hits_at_5 = 0
    hits_at_1 = 0

    print(
        f"\nhit-rate@5 | "
        f"чанк {config.CHUNK_SIZE}, "
        f"overlap {config.CHUNK_OVERLAP}"
    )

    for case in cases:

        expected_sources = case.get(
            "expected_sources",
            []
        )

        question_type = case.get(
            "type",
            "direct"
        )

        # out_of_scope не участвует в метрике
        if question_type == "out_of_scope":
            continue

        if not expected_sources:
            continue

        question = case.get("question", "").strip()

        if not question:
            continue

        evaluated += 1

        n_results = min(
            config.TOP_K,
            collection.count()
        )

        result = collection.query(
            query_texts=[question],
            n_results=n_results,
        )

        metadatas = result.get(
            "metadatas",
            [[]]
        )[0]

        found_sources = [
            metadata.get("source")
            for metadata in metadatas
        ]

        hit_5 = any(
            source in expected_sources
            for source in found_sources[:5]
        )

        hit_1 = bool(
            found_sources
            and found_sources[0] in expected_sources
        )

        if hit_5:
            hits_at_5 += 1

        if hit_1:
            hits_at_1 += 1

        status = "OK" if hit_5 else "MISS"

        print(
            f"  [{status}] "
            f"{question}"
        )

        print(
            f"      ожидалось: "
            f"{expected_sources}"
        )

        print(
            f"      найдено: "
            f"{found_sources[:5]}"
        )

    if evaluated == 0:
        print(
            "Нет вопросов, участвующих "
            "в оценке."
        )
        return

    rate_5 = hits_at_5 / evaluated * 100
    rate_1 = hits_at_1 / evaluated * 100

    print(
        f"\nhit-rate@5 = "
        f"{rate_5:.0f}% "
        f"({hits_at_5} из {evaluated})"
    )

    print(
        f"hit-rate@1 = "
        f"{rate_1:.0f}% "
        f"({hits_at_1} из {evaluated})"
    )


if __name__ == "__main__":
    ingest()
    evaluate_retrieval()