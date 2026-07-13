"""Update and render the WAMOCON handbook with the installed Microsoft Word.

This helper is intentionally a local QA tool.  Word performs the same field
and pagination work that an operator's desktop installation will perform;
PyMuPDF then creates one PNG per PDF page for visual inspection.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def render(docx_path: Path, output_dir: Path) -> tuple[Path, list[Path]]:
    try:
        import fitz
        import pythoncom
        import win32com.client
    except ImportError as exc:  # pragma: no cover - workstation preflight
        raise RuntimeError("Microsoft Word COM support and PyMuPDF are required") from exc

    docx_path = docx_path.resolve(strict=True)
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = output_dir / f"{docx_path.stem}.pdf"
    if pdf_path.exists():
        pdf_path.unlink()
    for stale_page in output_dir.glob("page-*.png"):
        stale_page.unlink()

    pythoncom.CoInitialize()
    word = None
    document = None
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        # msoAutomationSecurityForceDisable: never execute document macros.
        word.AutomationSecurity = 3
        document = word.Documents.Open(
            FileName=str(docx_path),
            ConfirmConversions=False,
            ReadOnly=False,
            AddToRecentFiles=False,
            Visible=False,
            OpenAndRepair=False,
            NoEncodingDialog=True,
        )
        document.Fields.Update()
        for index in range(1, document.TablesOfContents.Count + 1):
            document.TablesOfContents(index).Update()
        document.Save()
        # wdExportFormatPDF = 17.  The remaining values preserve hyperlinks,
        # bookmarks, and document-structure tags for an accessible QA render.
        document.ExportAsFixedFormat(
            OutputFileName=str(pdf_path),
            ExportFormat=17,
            OpenAfterExport=False,
            OptimizeFor=0,
            Range=0,
            Item=0,
            IncludeDocProps=True,
            KeepIRM=True,
            CreateBookmarks=1,
            DocStructureTags=True,
            BitmapMissingFonts=True,
            UseISO19005_1=False,
        )
    finally:
        if document is not None:
            document.Close(SaveChanges=False)
        if word is not None:
            word.Quit()
        pythoncom.CoUninitialize()

    if not pdf_path.is_file() or pdf_path.stat().st_size == 0:
        raise RuntimeError(f"Word did not create a PDF at {pdf_path}")

    page_paths: list[Path] = []
    with fitz.open(pdf_path) as pdf:
        if pdf.page_count == 0:
            raise RuntimeError("Word produced an empty PDF")
        for number, page in enumerate(pdf, start=1):
            page_path = output_dir / f"page-{number:03d}.png"
            page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False).save(page_path)
            page_paths.append(page_path)
    return pdf_path, page_paths


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the Word handbook for visual QA.")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("docs/WAMOCON-Marketing-Handbuch.docx"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("qa_output/handbook-render"),
    )
    args = parser.parse_args()
    pdf_path, page_paths = render(args.input, args.output_dir)
    print(f"PDF: {pdf_path}")
    print(f"Pages: {len(page_paths)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
