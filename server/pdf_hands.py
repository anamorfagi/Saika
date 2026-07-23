"""Приём PDF-чертежей (эвакуационные планы, техдокументация) — 2026-07-23.

Модель "видит" только растровые картинки, а PDF — векторный/страничный
контейнер. Здесь рендерим ОДНУ страницу в PNG (PyMuPDF/fitz) и дальше файл
идёт по уже существующему пути image (тот же LAST_IMAGE/vision, что и для
обычного прикреплённого фото) — никакой отдельной инфраструктуры для vision
заводить не пришлось.

Форматы вроде CorelDRAW (.cdr) и AutoCAD (.dwg) СЮДА не входят — это
проприетарные форматы без вменяемой открытой библиотеки для рендера;
единственный практичный мост — экспортировать их в PDF/PNG из самой
программы (один клик в Corel/AutoCAD) и уже это скармливать Сайке.
Новые .ai (Adobe Illustrator) обычно физически являются PDF-контейнером —
неплохой шанс, что тоже сработает через этот же путь, если бы отправлялись
(сейчас ui/index.html различает файлы только по MIME image/*|application/pdf,
.ai обычно отдаёт другой MIME и до сюда не доходит).

Требует PyMuPDF (пакет "PyMuPDF", импортируется как fitz) в .venv — не
входит в базовую установку, поставить один раз: setup/install_pdf_support.bat
"""
import base64
import logging

log = logging.getLogger("saika.pdf")

MAX_DIM = 2000        # больше — только раздувает base64 без пользы для vision-моделей
DEFAULT_ZOOM = 2.2    # ~158 DPI — читаемо для текста на плане, не слишком тяжело


def available() -> bool:
    try:
        import fitz  # noqa: F401
        return True
    except ImportError:
        return False


def to_image_data_url(pdf_data_url: str, page: int = 0,
                      zoom: float = DEFAULT_ZOOM) -> tuple[str, dict]:
    """pdf_data_url — 'data:application/pdf;base64,...' (как из браузера,
    FileReader.readAsDataURL). Возвращает (картинка_data_url, meta), где
    meta = {"pages": N, "page": использованная_страница (0-based), "w", "h"}.
    Бросает RuntimeError с понятным текстом на русском — main.py отдаёт его
    прямо пользователю через report_problem, отдельно ничего не оборачивать."""
    try:
        import fitz
    except ImportError:
        raise RuntimeError(
            "чтение PDF ещё не установлено — один раз запусти "
            "setup\\install_pdf_support.bat, потом перезапусти Сайку")
    if "," in pdf_data_url:
        _, b64 = pdf_data_url.split(",", 1)
    else:
        b64 = pdf_data_url
    try:
        raw = base64.b64decode(b64)
    except Exception as e:
        raise RuntimeError(f"не смогла разобрать PDF-файл: {e}")
    try:
        doc = fitz.open(stream=raw, filetype="pdf")
    except Exception as e:
        raise RuntimeError(f"не смогла открыть PDF (повреждён или не PDF?): {e}")
    if doc.page_count == 0:
        doc.close()
        raise RuntimeError("PDF пустой — страниц не нашла")
    page = max(0, min(page, doc.page_count - 1))
    pg = doc[page]
    mat = fitz.Matrix(zoom, zoom)
    pix = pg.get_pixmap(matrix=mat)
    # большие листы (A0/A1 чертежи) — не раздуваем сверх разумного максимума
    if max(pix.width, pix.height) > MAX_DIM:
        scale = MAX_DIM / max(pix.width, pix.height)
        pix = pg.get_pixmap(matrix=fitz.Matrix(zoom * scale, zoom * scale))
    png_bytes = pix.tobytes("png")
    meta = {"pages": doc.page_count, "page": page,
            "w": pix.width, "h": pix.height}
    doc.close()
    b64_png = base64.b64encode(png_bytes).decode("ascii")
    return "data:image/png;base64," + b64_png, meta
