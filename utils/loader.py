"""
업로드한 문서 1개를 받아서:
  1) 임시 폴더에 저장하고
  2) 워드(.docx)면 PDF로 변환하고
  3) 페이지별 텍스트를 추출하는
한 번에 처리하는 기능.

계약서와 제안서 둘 다 똑같이 이 함수를 사용합니다.
"""

import os
import tempfile

from utils.convert import convert_to_pdf
from utils.pdf_utils import extract_text_by_page


def process_uploaded_document(uploaded_file) -> dict:
    """
    uploaded_file : Streamlit file_uploader 가 준 업로드 객체
    반환값(dict)  : {
        "name": 원본 파일 이름,
        "pdf_path": 최종 PDF 경로,
        "pages": [{"page": 1, "text": "..."}, ...],
    }
    """
    # 1) 임시 폴더에 저장
    temp_dir = tempfile.mkdtemp()
    saved_path = os.path.join(temp_dir, uploaded_file.name)
    with open(saved_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    # 2) PDF가 아니면(워드/파워포인트) PDF로 변환
    file_ext = os.path.splitext(uploaded_file.name)[1].lower()
    if file_ext == ".pdf":
        pdf_path = saved_path
    else:
        pdf_path = convert_to_pdf(saved_path, temp_dir)

    # 3) 텍스트 추출
    pages = extract_text_by_page(pdf_path)

    return {
        "name": uploaded_file.name,
        "pdf_path": pdf_path,
        "pages": pages,
    }


def process_uploaded_documents(files: list) -> dict:
    """
    워드+PDF를 함께 올릴 수 있게, 여러 파일을 받아 하나의 결과로 정리.
    - 텍스트/페이지/이미지가 모두 같은 페이지를 가리키도록 '한 소스'만 사용.
    - 워드(글자층 확실) > PDF > 기타(PPT) 순으로 기준 파일 선택.
    반환값 : {"name", "pdf_path", "pages", "status"}
    """
    word = pdf = other = None
    for f in files:
        n = f.name.lower()
        if n.endswith((".docx", ".doc")) and word is None:
            word = f
        elif n.endswith(".pdf") and pdf is None:
            pdf = f
        elif other is None:
            other = f  # 파워포인트 등

    primary = word or pdf or other or files[0]
    result = process_uploaded_document(primary)

    # 상태 안내
    if word and pdf:
        status = "워드+PDF를 함께 올렸습니다. 텍스트는 글자 인식이 정확한 **워드**에서 읽었습니다."
    elif word:
        status = "워드 파일을 읽었습니다. (글자 인식이 정확합니다)"
    elif pdf:
        status = "PDF 파일을 읽었습니다. (스캔본이면 아래 OCR을 쓰거나 워드도 함께 올려주세요)"
    else:
        status = "파일을 읽었습니다."

    result["name"] = ", ".join(f.name for f in files)
    result["status"] = status
    return result
