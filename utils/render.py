"""
PyMuPDF(fitz)로 PDF의 특정 페이지를 이미지(PNG)로 만들고,
가능하면 찾은 내용 부분을 노란색으로 강조하는 기능.
"""

import fitz  # PyMuPDF


def render_page_image(
    pdf_path: str,
    page_number: int,
    highlight_text: str = "",
    zoom: float = 3.0,
) -> bytes:
    """
    pdf_path      : PDF 경로
    page_number   : 사람이 보는 페이지 번호(1부터)
    highlight_text: 강조하고 싶은 내용(원문). 페이지에서 찾으면 노란색 표시.
    zoom          : 이미지 확대 배율 (클수록 선명, 느림)
    반환값        : PNG 이미지 바이트 (st.image 에 바로 넣을 수 있음)
    """
    doc = fitz.open(pdf_path)

    # 페이지 번호 안전 처리
    index = (page_number or 1) - 1
    index = max(0, min(index, len(doc) - 1))
    page = doc[index]

    # 강조 표시 시도 (정확히 일치하는 부분만 찾아짐)
    if highlight_text:
        for snippet in _make_snippets(highlight_text):
            try:
                rects = page.search_for(snippet)
            except Exception:
                rects = []
            for rect in rects:
                page.add_highlight_annot(rect)
            if rects:
                break  # 하나라도 찾으면 충분

    # 글자/그림이 있는 부분만 잘라내기(원본의 빈 회색 여백 제거)
    clip = _content_bbox(page)

    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip)
    img_bytes = pix.tobytes("png")
    doc.close()
    return img_bytes


def _content_bbox(page):
    """
    페이지에서 실제 글자/그림이 있는 영역만 감싸는 사각형을 계산합니다.
    이 부분만 그리면 원본의 빈/회색 여백이 잘려서 내용이 꽉 차게 보입니다.
    내용을 못 찾으면 None(=페이지 전체)을 반환합니다.
    """
    boxes = []

    # 글자(단어) 영역
    try:
        for w in page.get_text("words"):
            boxes.append(fitz.Rect(w[:4]))
    except Exception:
        pass

    # 그림(이미지) 영역
    try:
        for img in page.get_images(full=True):
            for ir in page.get_image_rects(img[0]):
                boxes.append(ir)
    except Exception:
        pass

    if not boxes:
        return None  # 내용을 못 찾으면 페이지 전체를 그림

    rect = boxes[0]
    for b in boxes[1:]:
        rect |= b  # 모든 영역을 합침

    # 여백 약간 주고, 페이지 밖으로 안 나가게 다듬기
    rect += (-8, -8, 8, 8)
    rect &= page.rect

    if rect.is_empty or rect.is_infinite:
        return None
    return rect


def _make_snippets(text: str) -> list:
    """
    강조용으로 찾아볼 짧은 조각들을 만듭니다.
    LLM이 요약했을 수 있어 전체 문장은 안 찾아질 수 있으므로,
    앞부분 일부와 첫 줄을 후보로 씁니다.
    """
    text = " ".join(text.split())  # 공백 정리
    candidates = []
    if len(text) > 12:
        candidates.append(text[:25])  # 앞 25글자
    first_line = text.split(".")[0]
    if 6 < len(first_line) < 40:
        candidates.append(first_line)
    # 중복 제거
    seen = set()
    result = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            result.append(c)
    return result
