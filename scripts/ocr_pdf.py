#!/usr/bin/env python3
"""
OCR utility for image-based PDFs using PyMuPDF + EasyOCR.

Example:
  python scripts/ocr_pdf.py \
    --input frontend/src/roster/pdf/Aeldari.pdf \
    --output frontend/src/roster/pdf/Aeldari_ocr.txt \
    --lang en --scale 1.0
"""

from __future__ import annotations

import argparse
from pathlib import Path

import easyocr
import fitz


def run_ocr(
    input_pdf: Path,
    output_txt: Path,
    lang: str,
    gpu: bool,
    scale: float,
    paragraph: bool,
    model_dir: Path,
    download_models: bool,
) -> None:
    if not input_pdf.exists() or not input_pdf.is_file():
        raise FileNotFoundError(f"Input PDF not found: {input_pdf}")
    if scale <= 0:
        raise ValueError(f"--scale must be > 0 (got {scale})")
    if not lang.strip():
        raise ValueError("--lang cannot be empty")

    model_dir.mkdir(parents=True, exist_ok=True)
    output_txt.parent.mkdir(parents=True, exist_ok=True)

    reader = easyocr.Reader(
        [lang],
        gpu=gpu,
        model_storage_directory=str(model_dir),
        user_network_directory=str(model_dir),
        download_enabled=download_models,
        verbose=False,
    )

    document = fitz.open(str(input_pdf))
    total_pages = len(document)

    with output_txt.open("w", encoding="utf-8") as output_file:
        for page_index, page in enumerate(document, start=1):
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            page_image_bytes = pixmap.tobytes("png")
            lines = reader.readtext(page_image_bytes, detail=0, paragraph=paragraph)

            output_file.write(f"--- PAGE {page_index} ---\n")
            for line in lines:
                text = str(line).strip()
                if text:
                    output_file.write(text + "\n")
            output_file.write("\n")
            print(f"page {page_index}/{total_pages} done", flush=True)

    print(f"WROTE: {output_txt}")
    print(f"PAGES: {total_pages}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run OCR on an image-based PDF")
    parser.add_argument("--input", required=True, help="Input PDF path")
    parser.add_argument("--output", required=True, help="Output text file path")
    parser.add_argument(
        "--lang",
        default="en",
        help="EasyOCR language code (example: en, fr). Default: en",
    )
    parser.add_argument(
        "--gpu",
        action="store_true",
        help="Enable GPU OCR (default: CPU mode).",
    )
    parser.add_argument(
        "--scale",
        type=float,
        default=1.0,
        help="Rasterization scale factor for PDF pages. Higher = slower but often better OCR.",
    )
    parser.add_argument(
        "--paragraph",
        action="store_true",
        help="Group neighboring text boxes into paragraph-like lines.",
    )
    parser.add_argument(
        "--model-dir",
        default=".easyocr-models",
        help="Directory where EasyOCR models are stored/downloaded.",
    )
    parser.add_argument(
        "--download-models",
        action="store_true",
        help="Allow model download if not found locally (requires internet).",
    )
    args = parser.parse_args()

    run_ocr(
        input_pdf=Path(args.input),
        output_txt=Path(args.output),
        lang=args.lang,
        gpu=args.gpu,
        scale=args.scale,
        paragraph=args.paragraph,
        model_dir=Path(args.model_dir),
        download_models=args.download_models,
    )


if __name__ == "__main__":
    main()
