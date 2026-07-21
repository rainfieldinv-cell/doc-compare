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


# ── 클로드가 채워줄 결과의 '형식'(어떤 단계에서도 공용) ──────────
class ExtractFinding(BaseModel):
    group: str  # 이 내용이 속한 그룹(분류) 이름
    item: str  # 항목 이름 (예: 대출금액, 담보, 당연 EOD)
    content: str  # 이해하기 쉽게 정리한 내용
    quote: str = ""  # 근거가 된 계약서 '원문 그대로' (형광펜 표시용)
    page: Optional[int] = None  # 원본 페이지 번호


class ExtractResult(BaseModel):
    findings: List[ExtractFinding]


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


EXTRACT_SYSTEM = """당신은 금융 계약서·제안서를 검토하는 꼼꼼한 한국어 금융 분석 보조원입니다.
주어진 문서에서 요청한 항목에 해당하는 내용을 '의미 기준'으로 찾아냅니다.
제목만 보지 말고, 실제 의미가 해당하면 추출하세요.

규칙:
- 문서에 실제로 적힌 내용만 추출하세요. 추측하거나 지어내지 마세요.
- page 에는 그 내용이 등장한 [페이지 N] 표시의 숫자 N을 넣으세요.
- content 에는 이해하기 쉽게 정리한 내용을 담되 너무 길면 요약하세요.
- quote 에는 그 근거가 된 계약서 '원문 문장을 그대로' 복사하세요(요약·변형 금지). 이 문장으로 형광펜을 칠하므로 원문과 글자가 정확히 같아야 합니다. 너무 길면 핵심 한 문장만.
- item 에는 그 내용이 어떤 항목인지 짧은 한국어 이름을 적으세요.
- group 에는 아래 사용자가 제시한 '그룹명' 중 정확히 하나를 그대로 넣으세요.
- 해당 내용이 없으면 그 그룹은 비워 두세요(억지로 만들지 말 것)."""


def _extract(pages: list, doc_label: str, api_key: str,
             task_instructions: str, group_names: list) -> dict:
    """
    범용 추출기: 문서에서 task_instructions 가 설명한 항목들을 찾아
    {그룹명: [{"항목","내용","페이지"}, ...]} 형태로 반환.
    """
    client = anthropic.Anthropic(api_key=api_key)
    document_text = _build_page_marked_text(pages)

    user_prompt = (
        f"아래는 '{doc_label}' 문서의 전체 텍스트입니다.\n"
        f"{task_instructions}\n\n"
        f"각 내용을 group/item/content/quote/page 로 정리하세요. "
        f"group 은 반드시 다음 중 하나로 정확히 표기: {group_names}\n\n"
        f"문서 텍스트:\n\"\"\"\n{document_text}\n\"\"\""
    )

    response = client.messages.parse(
        model=MODEL,
        max_tokens=16000,
        system=EXTRACT_SYSTEM,
        messages=[{"role": "user", "content": user_prompt}],
        output_format=ExtractResult,
    )
    return _group_findings(response.parsed_output.findings, group_names)


def _group_findings(findings: list, group_names: list) -> dict:
    """ExtractFinding 목록을 그룹별 딕셔너리로 묶습니다(그룹 순서 유지)."""
    def norm(s):
        return (s or "").replace(" ", "")

    name_by_norm = {norm(g): g for g in group_names}
    out = {g: [] for g in group_names}  # 그룹 순서대로 초기화

    for f in findings:
        rec = {
            "항목": (f.item or "").strip(),
            "내용": (f.content or "").strip(),
            "원문": (f.quote or "").strip(),
            "페이지": f.page,
        }
        key = name_by_norm.get(norm(f.group))
        if key:
            out[key].append(rec)
        else:
            # 예상 못 한 그룹명이면 잃어버리지 않게 그대로 보관
            out.setdefault((f.group or "기타").strip(), []).append(rec)
    return out


# ── 3단계: 금융조건만 찾기 ──────────────────────────
FINANCIAL_GROUPS = ["금융조건"]
FINANCIAL_TASK = (
    "이 문서에서 '금융조건'에 해당하는 내용을 모두 찾으세요. "
    "예: 대출/투자 금액, 금리(이자율), 만기, 상환방식, 수수료, 연체이자, 이자지급주기 등. "
    "찾은 내용의 group 은 모두 '금융조건' 으로 하세요."
)


def analyze_financial(pages: list, doc_label: str, api_key: str) -> dict:
    """3단계: {'금융조건': [...]} 반환."""
    return _extract(pages, doc_label, api_key, FINANCIAL_TASK, FINANCIAL_GROUPS)


# ── 5단계: 권리·통제 구조(4개 그룹) 찾기 ──────────────
RIGHTS_GROUPS = ["반영 확인", "의사결정", "담보 실행", "기한이익상실(EOD)"]
RIGHTS_TASK = """이 문서에서 아래 4개 그룹에 해당하는 '권리·통제 구조' 내용을 찾으세요.
각 내용을 알맞은 group 으로 분류하세요(아래 그룹명을 정확히 사용).

[반영 확인]
- 선행조건, 후행조건, 채권보전 조건이 제안서(IM)와 맞게 반영되어 있는지
- 금액, 금리가 제대로 반영되어 있는지
[의사결정]
- 대리금융기관(대리은행) 단독 결정 사항
- 다수대주(과반/특정비율 동의) 의사결정 사항 (있는 대로 항목별 리스팅)
- 전원대주(전원 동의) 의사결정 사항 (항목별 리스팅)
- 일부 대주가 다수대주 요건을 충족하는지 여부
[담보 실행]
- 각 트렌치(Tranche) 대주가 담보를 단독으로 처분(실행)할 권리가 있는지 여부
- 공매(공개매각)권 실행에 있어 후순위 트렌치의 제약 사항
[기한이익상실(EOD)]
- 당연(자동) 기한이익상실 사유 (항목별 리스팅)
- 기타(통지·청구형 등) 기한이익상실 사유 (항목별 리스팅)"""


EXTRA_KEYWORD_GROUP = "추가 키워드(시트)"


def analyze_rights(pages: list, doc_label: str, api_key: str,
                   extra_keywords: list = None) -> dict:
    """
    5단계: 4개 기본 그룹 + (선택) 구글 시트의 '추가 키워드' 를 함께 찾음.
    extra_keywords 가 있으면 '추가 키워드(시트)' 그룹으로 결과가 추가됩니다.
    """
    task = RIGHTS_TASK
    groups = list(RIGHTS_GROUPS)

    kws = [k for k in (extra_keywords or []) if k and k.strip()]
    if kws:
        groups.append(EXTRA_KEYWORD_GROUP)
        joined = ", ".join(kws)
        task += (
            f"\n\n[추가 키워드(시트)]\n"
            f"아래 키워드 각각에 대해, 문서에서 그 키워드와 '의미상 관련된' 내용을 찾으세요. "
            f"찾은 내용의 group 은 '{EXTRA_KEYWORD_GROUP}' 으로 하고, "
            f"item 에는 어떤 키워드에 해당하는지 그 키워드 이름을 적으세요. "
            f"제목 글자만 보지 말고 실제 의미가 맞으면 추출하세요. "
            f"문서에 관련 내용이 없는 키워드는 억지로 만들지 마세요.\n"
            f"키워드 목록: {joined}"
        )

    return _extract(pages, doc_label, api_key, task, groups)


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
