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

# Публичные ссылки на handbook по годам поступления.
# У каждого потока свои требования, поэтому год — обязательный ключ:
# второкурснику нельзя советовать по правилам чужого года.
HANDBOOK_SOURCES = {
    2023: "https://www.canva.com/design/DAFlThZErSU/SMtWNa2xo-hGC4aca9y1gg/view",
    2024: "https://www.canva.com/design/DAGH5nfr2_Q/CZO4-kHrZNWEcjjPjo2lVw/view",
    2025: "https://www.canva.com/design/DAGqrtAh0Vc/dKOWX8f_JUstJqoyg_w-6Q/view",
    2026: "https://canva.link/9hvxc82txd4jj08",
}


def handbook_path(year: int) -> Path:
    return DATA_RAW / f"handbook_{year}.json"
