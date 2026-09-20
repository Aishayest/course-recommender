"""Пути и параметры проекта."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DATA_RAW = ROOT / "data" / "raw"
DATA_INTERIM = ROOT / "data" / "interim"
DATA_PROCESSED = ROOT / "data" / "processed"

# Модель для эмбеддингов курсов. Multilingual — каталог может быть
# на русском, казахском и английском вперемешку.
EMBEDDING_MODEL = "intfloat/multilingual-e5-base"

# Веса итоговой полезности: релевантность / шанс попасть / ожидаемая оценка.
UTILITY_WEIGHTS = {"relevance": 0.5, "availability": 0.35, "grade": 0.15}

TOP_K_CANDIDATES = 50
TOP_K_RECOMMENDATIONS = 5
