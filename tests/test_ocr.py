"""OCR не должен падать до распознавания из-за неверного типа буфера."""

from pathlib import Path


def run():
    source = (Path(__file__).resolve().parents[1] / "anamorf" / "ocr.py")
    text = source.read_text(encoding="utf-8")
    good = "CryptographicBuffer.create_from_byte_array(bgra.tobytes())"
    bad = "CryptographicBuffer.create_from_byte_array(list(bgra.tobytes()))"
    return [("Windows OCR получает байты, а не список чисел",
             good in text and bad not in text,
             "bytes-like буфер передаётся в Windows Runtime")]
