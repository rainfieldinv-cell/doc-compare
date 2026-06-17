"""
스캔(사진) PDF의 글자를 클로드(Claude) 비전으로 읽어내는 OCR 기능.

PyMuPDF로 각 페이지를 이미지로 만든 뒤, 클로드에게 "이 페이지의 글자를
그대로 옮겨 적어줘"라고 요청해서 텍스트를 얻습니다.
"""

import base64

import anthropic
import fitz  # PyMuPDF

# OCR(글자 옮겨 적기)에는 빠르고 저렴한 모델로도 충분합니다.
# 더 높은 정확도를 원하면 "claude-opus-4-8" 로 바꿀 수 있습니다.
OCR_MODEL = "claude-sonnet-4-6"

OCR_PROMPT = (
    "이 이미지는 한국어 금융 문서(계약서/제안서)의 한 페이지입니다. "
    "페이지에 보이는 모든 글자를 빠짐없이 그대로 옮겨 적어 주세요. "
    "표는 가능한 한 읽기 쉽게 정리하되 내용을 바꾸지 마세요. "
    "설명이나 해설은 붙이지 말고, 옮겨 적은 글자만 출력하세요. "
    "글자가 전혀 없으면 빈 줄로 두세요."
)


def ocr_pdf_pages(pdf_path: str, api_key: str, zoom: float = 2.0,
                  progress_callback=None) -> list:
    """
    pdf_path         : OCR 할 PDF 경로
    api_key          : Anthropic API 키
    zoom             : 이미지 확대 배율(클수록 또렷하지만 비용 증가)
    progress_callback: (현재페이지, 전체페이지) 를 받는 함수(진행률 표시용)
    반환값           : [{"page":1,"text":"..."}, ...]
    """
    client = anthropic.Anthropic(api_key=api_key)
    doc = fitz.open(pdf_path)
    results = []
    total = len(doc)

    for index in range(total):
        page = doc[index]
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        img_b64 = base64.standard_b64encode(pix.tobytes("png")).decode("utf-8")

        try:
            message = client.messages.create(
                model=OCR_MODEL,
                max_tokens=4000,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": img_b64,
                                },
                            },
                            {"type": "text", "text": OCR_PROMPT},
                        ],
                    }
                ],
            )
            text = "".join(
                b.text for b in message.content if b.type == "text"
            ).strip()
        except Exception as e:
            text = f"(이 페이지 OCR 실패: {e})"

        results.append({"page": index + 1, "text": text})

        if progress_callback:
            progress_callback(index + 1, total)

    doc.close()
    return results
