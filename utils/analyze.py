"""
문서 텍스트에서 '금융조건'과 '채권보전조치'에 해당하는 내용을
Anthropic(클로드, Claude)로 찾아내는 기능.

- 제목이 아니라 '의미상' 해당하는 문장/문단을 찾습니다.
- 각 내용이 원본 몇 페이지에 있는지(페이지 번호)도 함께 받아옵니다.
- 결과 형식이 흐트러지지 않게 구조화 출력(structured output)을 사용합니다.
"""

import json
from typing import List, Optional

import anthropic
from pydantic import BaseModel

# 사용할 모델. 품질을 높이려면 그대로(opus), 비용을 아끼려면
# "claude-sonnet-4-6" 또는 "claude-haiku-4-5" 로 바꾸면 됩니다.
MODEL = "claude-opus-4-8"


# ── 클로드가 채워줄 결과의 '형식'을 미리 정의 ──────────────
class Finding(BaseModel):
    item: str  # 항목 이름 (예: 대출금액, 담보)
    content: str  # 원문 핵심 내용
    page: Optional[int] = None  # 원본 페이지 번호


class DocAnalysis(BaseModel):
    financial_conditions: List[Finding]  # 금융조건 목록
    creditor_protections: List[Finding]  # 채권보전조치 목록


# 분석에서 통째로 제외할 페이지 제목(공백 무시하고 비교).
# 자체적으로 만드는 요약/개요 페이지라 비교 대상이 아닌 것들을 여기 추가.
EXCLUDE_PAGE_KEYWORDS = [
    "본건사모사채개요",  # "1.1 본 건 사모사채 개요" 요약 슬라이드
]


def _is_excluded_page(text: str) -> bool:
    """이 페이지가 제외 대상 제목을 포함하는지(공백 무시)."""
    norm = text.replace(" ", "").replace("\n", "").replace("\t", "")
    return any(k in norm for k in EXCLUDE_PAGE_KEYWORDS)


def _build_page_marked_text(pages: list) -> str:
    """
    페이지 번호를 표시한 텍스트로 합칩니다. 클로드가 페이지를 인용할 수 있게.
    EXCLUDE_PAGE_KEYWORDS 에 걸리는 페이지는 건너뜁니다(요약/개요 페이지 제외).
    """
    blocks = []
    for item in pages:
        if _is_excluded_page(item["text"]):
            continue  # 제외 대상 페이지는 분석에 넣지 않음
        blocks.append(f"[페이지 {item['page']}]\n{item['text']}")
    return "\n\n".join(blocks)


SYSTEM_PROMPT = """당신은 금융 계약서·제안서를 검토하는 꼼꼼한 한국어 금융 분석 보조원입니다.
주어진 문서 텍스트에서 '금융조건'과 '채권보전조치'에 해당하는 내용을 의미 기준으로 찾아냅니다.
제목만 보지 말고, 실제 의미가 해당하면 추출하세요.

[금융조건 예시] 대출/투자 금액, 금리(이자율), 만기, 상환방식, 수수료, 연체이자, 이자지급주기 등
[채권보전조치 예시] 담보, 근저당, 질권, 보증, 연대보증, 에스크로, 재무약정(covenant), 기한이익상실, 우선변제 등

규칙:
- 문서에 실제로 적힌 내용만 추출하세요. 추측하거나 지어내지 마세요.
- 각 항목의 page에는 그 내용이 등장한 [페이지 N] 표시의 숫자 N을 넣으세요.
- content에는 원문의 핵심 문장을 최대한 그대로 담되 너무 길면 요약하세요.
- item에는 그 내용이 어떤 항목인지 짧은 한국어 이름을 적으세요(예: 대출금액, 담보).
- 해당 내용이 없으면 빈 목록으로 두세요."""

USER_PROMPT_TEMPLATE = """아래는 '{doc_label}' 문서의 전체 텍스트입니다.
금융조건(financial_conditions)과 채권보전조치(creditor_protections)를 찾아 정리해 주세요.

문서 텍스트:
\"\"\"
{document_text}
\"\"\""""


def analyze_document(pages: list, doc_label: str, api_key: str) -> dict:
    """
    pages    : extract_text_by_page 결과 [{"page":1,"text":"..."}, ...]
    doc_label: "계약서" 또는 "제안서"
    api_key  : Anthropic API 키
    반환값   : {"금융조건": [...], "채권보전조치": [...]}
               각 항목은 {"항목","내용","페이지"} 형태
    """
    client = anthropic.Anthropic(api_key=api_key)

    document_text = _build_page_marked_text(pages)
    user_prompt = USER_PROMPT_TEMPLATE.format(
        doc_label=doc_label,
        document_text=document_text,
    )

    # 구조화 출력: 위에서 정의한 DocAnalysis 형식으로 받기
    response = client.messages.parse(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
        output_format=DocAnalysis,
    )

    result = response.parsed_output

    # 화면(app.py)이 쓰는 한국어 키 형태로 변환
    return {
        "금융조건": _to_korean(result.financial_conditions),
        "채권보전조치": _to_korean(result.creditor_protections),
    }


def _to_korean(findings: List[Finding]) -> list:
    """Finding 목록을 {"항목","내용","페이지"} 딕셔너리 목록으로 변환."""
    out = []
    for f in findings:
        out.append(
            {
                "항목": (f.item or "").strip(),
                "내용": (f.content or "").strip(),
                "페이지": f.page,
            }
        )
    return out


# ════════════════════════════════════════════
# 4단계: 계약서 vs 제안서 비교·정리
# ════════════════════════════════════════════
class ComparisonRow(BaseModel):
    category: str  # "금융조건" 또는 "채권보전조치"
    item: str  # 비교 항목 이름 (예: 금리, 담보)
    contract_value: str  # 계약서 내용 (없으면 빈칸)
    contract_page: Optional[int] = None  # 계약서 원본 페이지
    im_value: str  # 제안서 내용 (없으면 빈칸)
    im_page: Optional[int] = None  # 제안서 원본 페이지
    status: str  # "일치" / "차이" / "계약서에만 있음" / "제안서에만 있음"
    fix_instruction: str  # 제안서를 계약서에 맞추려면 어떻게 고칠지 (일치면 빈칸)


class Comparison(BaseModel):
    rows: List[ComparisonRow]
    summary: str  # 전체 총평 (한두 문단)


COMPARE_SYSTEM = """당신은 금융 계약서와 제안서를 대조 검토하는 한국어 금융 분석 보조원입니다.
'계약서'가 기준(정답)이고, '제안서'가 계약서에 맞는지 항목별로 비교합니다.

규칙:
- 두 문서의 같은 의미 항목끼리 묶어 한 줄(row)로 만드세요(예: 계약서의 '금리'와 제안서의 '이자율').
- status는 다음 중 하나로:
  · "일치": 내용이 사실상 같음
  · "차이": 같은 항목인데 값/조건이 다름
  · "계약서에만 있음": 제안서에 빠진 항목
  · "제안서에만 있음": 계약서에 없는데 제안서에만 있는 항목
- fix_instruction(수정지시)은 계약서를 기준으로 제안서를 어떻게 고쳐야 하는지 구체적으로 적으세요.
  status가 "일치"면 빈칸으로 두세요.
- contract_page에는 그 항목의 계약서 원본 페이지 번호(입력 데이터의 '페이지' 값)를 넣으세요.
  im_page에는 제안서 원본 페이지 번호를 넣으세요. 해당 문서에 없으면 비워 두세요.
- 추측하거나 지어내지 말고, 주어진 내용만 근거로 판단하세요.
- summary에는 차이가 큰 핵심 항목 위주로 전체 총평을 적으세요."""

COMPARE_PROMPT = """아래는 3단계에서 찾아낸 계약서와 제안서의 핵심 내용입니다(JSON).
'계약서'를 기준으로 '제안서'를 항목별로 비교해 표(rows)와 총평(summary)을 만들어 주세요.

데이터:
{data}"""


def compare_findings(contract_findings: dict, im_findings: dict,
                     api_key: str) -> Comparison:
    """
    contract_findings / im_findings : analyze_document 결과
    반환값 : Comparison (rows + summary)
    """
    client = anthropic.Anthropic(api_key=api_key)

    payload = {"계약서": contract_findings, "제안서": im_findings}
    user_prompt = COMPARE_PROMPT.format(
        data=json.dumps(payload, ensure_ascii=False, indent=2)
    )

    response = client.messages.parse(
        model=MODEL,
        max_tokens=16000,
        system=COMPARE_SYSTEM,
        messages=[{"role": "user", "content": user_prompt}],
        output_format=Comparison,
    )
    return response.parsed_output
