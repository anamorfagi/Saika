"""Вшитые субтитры из видео → таймкодированный JSONL-корпус.

Нужны PyAV, OpenCV, numpy и Windows OCR из ``anamorf.ocr``. Текст не
выводится в консоль: ролик может быть личным; в stdout остаётся только
счётчик строк. По умолчанию берётся нижняя часть кадра и один кадр раз в
0.75 с — этого достаточно для обычных двухсекундных реплик.
"""

from __future__ import annotations

import argparse
import json
import sys
from difflib import SequenceMatcher
from pathlib import Path

import av

# При ``python pipeline/subtitle_ocr.py`` sys.path указывает на pipeline/,
# а не на корень Сайки, где лежит anamorf/.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from anamorf.ocr import _winrt_read


def clean(text: str) -> str:
    return " ".join((text or "").replace("\n", " ").split())


def close_enough(left: str, right: str) -> bool:
    """Одна и та же реплика иногда читается с одной OCR-ошибкой."""
    if left == right:
        return True
    if not left or not right:
        return False
    return SequenceMatcher(None, left.casefold(), right.casefold()).ratio() >= 0.74


def is_overlay(text: str) -> bool:
    """Водяные знаки и технические титры не являются репликами."""
    folded = text.casefold()
    return any(mark in folded for mark in (
        "hentaih", "text 01", "a-spot", "pin-point", "seven", "mediabank",
    ))


def extract(video: Path, output: Path, stride: float, crop_start: float) -> list[dict[str, object]]:
    container = av.open(str(video))
    stream = container.streams.video[0]
    next_at = 0.0
    rows: list[dict[str, object]] = []

    try:
        for frame in container.decode(stream):
            if frame.time is None or frame.time + 0.001 < next_at:
                continue
            now = float(frame.time)
            next_at = now + stride
            image = frame.to_ndarray(format="bgr24")
            subtitle_area = image[int(image.shape[0] * crop_start):]
            text = clean(_winrt_read(subtitle_area))
            if not text or is_overlay(text):
                continue
            if (rows and now - float(rows[-1]["end"]) <= 3.5
                    and close_enough(str(rows[-1]["text"]), text)):
                rows[-1]["end"] = round(now, 2)
                continue
            rows.append({"start": round(now, 2), "end": round(now, 2), "text": text})
    finally:
        container.close()

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return rows


def write_observer_text(rows: list[dict[str, object]], output: Path) -> None:
    """Формат ``observer.py``: одна реплика с отметкой m:ss на строку."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            second = int(float(row["start"]))
            handle.write(f"[{second // 60}:{second % 60:02d}] {row['text']}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--plain-out", type=Path,
                        help="дополнительно записать [m:ss] текст для observer.py")
    parser.add_argument("--stride", type=float, default=0.75)
    parser.add_argument("--crop-start", type=float, default=0.62)
    args = parser.parse_args()
    if args.stride <= 0 or not 0 < args.crop_start < 1:
        parser.error("--stride > 0; --crop-start between 0 and 1")
    rows = extract(args.video, args.out, args.stride, args.crop_start)
    if args.plain_out:
        write_observer_text(rows, args.plain_out)
    print(f"{args.out}: {len(rows)} реплик")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
