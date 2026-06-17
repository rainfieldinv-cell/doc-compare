"""
워드(.docx/.doc)·파워포인트(.pptx/.ppt) 파일을 PDF로 변환하는 기능.

- 워드: docx2pdf(MS Word) → 안 되면 LibreOffice
- 파워포인트: MS PowerPoint(COM) → 안 되면 LibreOffice
변환된 PDF는 그 뒤 PDF와 똑같이 처리됩니다.
"""

import os
import shutil
import subprocess


def convert_to_pdf(input_path: str, output_dir: str) -> str:
    """
    파일 확장자를 보고 알맞은 변환 함수를 호출합니다.
    PDF가 아닌 워드/파워포인트를 PDF로 바꿔 그 경로를 반환합니다.
    """
    os.makedirs(output_dir, exist_ok=True)
    ext = os.path.splitext(input_path)[1].lower()

    if ext in (".docx", ".doc"):
        return _convert_word_to_pdf(input_path, output_dir)
    if ext in (".pptx", ".ppt"):
        return _convert_ppt_to_pdf(input_path, output_dir)

    raise RuntimeError(f"지원하지 않는 파일 형식입니다: {ext}")


def _pdf_target(input_path: str, output_dir: str) -> str:
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    return os.path.join(output_dir, base_name + ".pdf")


# ─────────────────────────────────────────────
# 워드 → PDF
# ─────────────────────────────────────────────
def _convert_word_to_pdf(docx_path: str, output_dir: str) -> str:
    pdf_path = _pdf_target(docx_path, output_dir)

    # 방법 1) MS Word 자동화(COM) — .doc / .docx 둘 다 가장 안정적
    try:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        word = None
        try:
            word = win32com.client.Dispatch("Word.Application")
            word.Visible = False
            word.DisplayAlerts = 0  # 경고창 끔
            document = word.Documents.Open(
                os.path.abspath(docx_path), ReadOnly=True, AddToRecentFiles=False
            )
            # 17 = PDF 형식(wdFormatPDF)
            document.SaveAs(os.path.abspath(pdf_path), FileFormat=17)
            document.Close(SaveChanges=False)
        finally:
            if word is not None:
                word.Quit()
            pythoncom.CoUninitialize()

        if os.path.exists(pdf_path):
            return pdf_path
    except Exception:
        pass

    # 방법 2) docx2pdf (신형 .docx 전용)
    try:
        from docx2pdf import convert as docx2pdf_convert

        docx2pdf_convert(docx_path, pdf_path)
        if os.path.exists(pdf_path):
            return pdf_path
    except Exception:
        pass

    # 방법 3) LibreOffice
    if _libreoffice_convert(docx_path, output_dir) and os.path.exists(pdf_path):
        return pdf_path

    raise RuntimeError(
        "워드 파일을 PDF로 변환하지 못했습니다.\n"
        "MS Word 또는 LibreOffice가 설치돼 있는지 확인하거나,\n"
        "직접 PDF로 저장한 뒤 PDF 파일을 업로드해 주세요."
    )


# ─────────────────────────────────────────────
# 파워포인트 → PDF
# ─────────────────────────────────────────────
def _convert_ppt_to_pdf(ppt_path: str, output_dir: str) -> str:
    pdf_path = _pdf_target(ppt_path, output_dir)

    # 방법 1) MS PowerPoint 자동화(COM)
    try:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        powerpoint = None
        try:
            powerpoint = win32com.client.Dispatch("PowerPoint.Application")
            presentation = powerpoint.Presentations.Open(
                os.path.abspath(ppt_path), WithWindow=False
            )
            # 32 = PDF 형식으로 저장(ppSaveAsPDF)
            presentation.SaveAs(os.path.abspath(pdf_path), 32)
            presentation.Close()
        finally:
            if powerpoint is not None:
                powerpoint.Quit()
            pythoncom.CoUninitialize()

        if os.path.exists(pdf_path):
            return pdf_path
    except Exception:
        pass

    # 방법 2) LibreOffice
    if _libreoffice_convert(ppt_path, output_dir) and os.path.exists(pdf_path):
        return pdf_path

    raise RuntimeError(
        "파워포인트 파일을 PDF로 변환하지 못했습니다.\n"
        "MS PowerPoint 또는 LibreOffice가 설치돼 있는지 확인하거나,\n"
        "직접 PDF로 저장한 뒤 PDF 파일을 업로드해 주세요."
    )


# ─────────────────────────────────────────────
# LibreOffice 공통 변환
# ─────────────────────────────────────────────
def _libreoffice_convert(input_path: str, output_dir: str) -> bool:
    soffice = _find_soffice()
    if not soffice:
        return False
    try:
        subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf",
             "--outdir", output_dir, input_path],
            check=True,
            timeout=180,
        )
        return True
    except Exception:
        return False


def _find_soffice():
    """LibreOffice 실행파일(soffice) 위치를 찾습니다. 없으면 None."""
    for name in ("soffice", "soffice.exe"):
        found = shutil.which(name)
        if found:
            return found
    candidates = [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None
