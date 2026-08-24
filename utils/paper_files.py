import re
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
PAPER_DIRS = [BASE_DIR / "papers", BASE_DIR / "Papers"]


def normalize(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()


def paper_files():
    files = []
    seen = set()
    for directory in PAPER_DIRS:
        if directory.exists():
            for path in directory.rglob("*"):
                key = str(path.resolve()).lower()
                if path.is_file() and key not in seen:
                    seen.add(key)
                    files.append(path)
    return files


def find_paper_file(paper_number, title):
    files = paper_files()
    if not files:
        return None

    number_pattern = re.compile(rf"(^|[^0-9])0*{int(paper_number)}([^0-9]|$)")
    for path in files:
        if number_pattern.search(path.stem):
            return path

    title_words = set(normalize(title).split())
    best_path = None
    best_score = 0
    for path in files:
        file_words = set(normalize(path.stem).split())
        score = len(title_words & file_words)
        if score > best_score:
            best_score = score
            best_path = path

    return best_path if best_score >= 3 else None


def download_mime(path):
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "application/pdf"
    if suffix == ".docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if suffix == ".xlsx":
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return "application/octet-stream"
