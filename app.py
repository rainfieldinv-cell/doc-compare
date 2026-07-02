"""
계약서·제안서(IM) 비교 도구
--------------------------------
[1단계] 계약서 텍스트 추출
[2단계] 제안서(IM) 텍스트 추출
        → 두 문서를 각각 업로드하면, 워드는 PDF로 바꾸고
          모든 페이지의 텍스트를 페이지 번호와 함께 추출해 보여줍니다.

실행 방법 (터미널):
    streamlit run app.py
"""

import os
import uuid

import streamlit as st

from utils.analyze import (
    RIGHTS_GROUPS,
    analyze_financial,
    analyze_rights,
    compare_findings,
)
from utils.auth import require_password
from utils.loader import process_uploaded_document
from utils.memo import load_memos, save_memos
from utils.ocr import ocr_pdf_pages
from utils.pdf_utils import join_all_text
from utils.render import render_page_image


# ─────────────────────────────────────────────
# Anthropic(클로드) API 키 가져오기 (secrets.toml 또는 환경변수)
# ─────────────────────────────────────────────
def get_api_key():
    key = st.secrets.get("anthropic_api_key", None)
    if not key:
        key = os.environ.get("ANTHROPIC_API_KEY")
    return key


# 페이지 이미지는 같은 입력이면 다시 안 만들도록 캐시(속도 향상)
@st.cache_data(show_spinner=False)
def cached_page_image(pdf_path: str, page: int, highlight: str) -> bytes:
    return render_page_image(pdf_path, page, highlight_text=highlight)


# 분석 결과(3~6단계)만 지우는 키 목록
_ANALYSIS_KEYS = [
    "findings_contract",
    "findings_im",
    "rights_contract",
    "rights_im",
    "comparison",
    "comparison_rights",
]


def clear_analysis_results():
    """분석 결과(핵심내용·비교)를 모두 지웁니다. (원본 문서는 유지)"""
    for k in _ANALYSIS_KEYS:
        st.session_state.pop(k, None)
    # 확인 체크박스 등 부수 상태도 정리
    for k in list(st.session_state.keys()):
        if k.startswith(("v4_", "v6_", "verified_")):
            st.session_state.pop(k, None)


def reset_all():
    """초기화 버튼: 올린 문서 + 분석 결과 + 화면 위치를 처음 상태로."""
    clear_analysis_results()
    for k in ["contract", "im", "uploader_contract", "uploader_im",
              "section", "sub_read", "sub_fin", "sub_rights",
              "fulltext_contract", "fulltext_im"]:
        st.session_state.pop(k, None)


# ─────────────────────────────────────────────
# 화면 기본 설정
# ─────────────────────────────────────────────
st.set_page_config(page_title="계약서·제안서(IM) 비교", layout="wide")

# 🔒 비밀번호 확인 (맞아야 아래 화면이 보임)
require_password()

# 사이드바 메뉴 (어느 화면인지 먼저 확인 → 제목 옆 초기화 버튼 표시 여부 결정)
st.sidebar.title("메뉴")
menu = st.sidebar.radio(
    "화면 선택",
    ["비교", "메모"],
    label_visibility="collapsed",
)

st.title("📑 계약서·제안서(IM) 비교")

# 안내문 (법적 판단 아님)
st.warning(
    "⚠️ 이 도구의 결과는 **법적 판단이 아니라 검토 보조용**입니다. "
    "중요한 결정은 반드시 담당자가 원본 문서를 직접 확인하세요."
)


# ─────────────────────────────────────────────
# 문서 1개를 처리하고 화면에 보여주는 공통 함수
# ─────────────────────────────────────────────
def render_document_section(label: str, session_key: str):
    """
    label       : 화면에 보일 이름 ("계약서" 또는 "제안서")
    session_key : 결과를 저장해 둘 이름 ("contract" 또는 "im")
    """
    st.header(f"{label} 업로드")

    uploaded = st.file_uploader(
        f"{label} 파일을 올려주세요 (PDF / 워드 .docx / 파워포인트 .pptx)",
        type=["pdf", "docx", "doc", "pptx", "ppt"],
        key=f"uploader_{session_key}",  # 탭마다 업로더를 구분
    )

    if uploaded is None:
        st.info(f"위에 {label} 파일(PDF / 워드 / 파워포인트)을 올리면 텍스트 추출이 시작됩니다.")
        return

    # 같은 파일은 한 번만 처리 (새로고침 때마다 다시 읽지 않도록,
    # 특히 OCR로 읽어둔 결과가 날아가지 않도록 보관)
    file_sig = f"{uploaded.name}-{uploaded.size}"
    saved = st.session_state.get(session_key)

    if saved and saved.get("_sig") == file_sig:
        result = saved  # 이미 처리(또는 OCR)한 결과 그대로 사용
    else:
        # 새(다른) 문서가 올라오면 이전 문서로 만든 분석 결과는 지운다
        # (계약서/제안서 중 하나만 바꿔도 비교는 둘을 함께 쓰므로 전부 초기화)
        if saved is not None:
            clear_analysis_results()
        with st.spinner(f"{label}을(를) 읽는 중..."):
            try:
                result = process_uploaded_document(uploaded)
            except Exception as e:
                st.error(str(e))
                return
        result["_sig"] = file_sig
        st.session_state[session_key] = result

    pages = result["pages"]
    total_pages = len(pages)
    total_chars = sum(len(p["text"]) for p in pages)

    st.success(f"업로드·추출 완료: {result['name']}")
    st.write(f"총 **{total_pages}페이지**, 글자 수 약 **{total_chars:,}자** 를 읽었습니다.")

    # 글자가 거의 없으면 = 스캔(사진) PDF → OCR 안내 + 버튼
    avg_chars = total_chars / total_pages if total_pages else 0
    if avg_chars < 20:
        st.warning(
            "텍스트가 거의 추출되지 않았습니다. **스캔(사진)으로 만들어진 PDF**로 보입니다. "
            "아래 버튼을 누르면 클로드가 페이지 사진을 읽어 글자로 바꿉니다(OCR). "
            f"({total_pages}페이지 처리에 몇 분, 소액 과금이 있을 수 있어요.)"
        )

        if st.button(f"🔎 {label} OCR로 글자 읽기", key=f"ocr_{session_key}"):
            api_key = get_api_key()
            if not api_key:
                st.error(
                    "Anthropic(클로드) API 키가 설정되지 않았습니다. "
                    "`.streamlit/secrets.toml` 의 `anthropic_api_key` 를 확인하세요."
                )
            else:
                progress = st.progress(0.0, text="OCR 준비 중...")

                def _cb(done, total):
                    progress.progress(
                        done / total,
                        text=f"OCR 진행 중... {done}/{total} 페이지",
                    )

                ocr_pages = ocr_pdf_pages(
                    result["pdf_path"], api_key, progress_callback=_cb
                )
                result["pages"] = ocr_pages  # 읽어낸 글자로 교체
                st.session_state[session_key] = result
                st.success("OCR 완료! 글자를 다시 읽었습니다.")
                st.rerun()

    # 페이지별 보기
    st.subheader("페이지별 텍스트")
    for item in pages:
        with st.expander(f"{item['page']} 페이지 (글자 수 {len(item['text'])})"):
            if item["text"]:
                st.text(item["text"])
            else:
                st.caption("(이 페이지에서는 텍스트가 추출되지 않았습니다)")

    # 전체 텍스트 한 번에 보기
    st.subheader("전체 텍스트 (한 번에 보기)")
    st.text_area(
        "전체 텍스트",
        value=join_all_text(pages),
        height=400,
        label_visibility="collapsed",
        key=f"fulltext_{session_key}",
    )


# ─────────────────────────────────────────────
# 3단계: 찾은 내용을 한쪽 열에 그려주는 함수
# ─────────────────────────────────────────────
def render_findings_column(label: str, doc_data: dict, findings: dict,
                           categories):
    """
    label      : "계약서" 또는 "제안서"
    doc_data   : st.session_state 의 문서 데이터 (pdf_path 등)
    findings   : 분석 결과 {그룹명: [...]}
    categories : 표시할 그룹명 순서 리스트
    """
    st.subheader(f"📌 {label}에서 찾은 내용")

    for category in categories:
        items = findings.get(category, [])
        st.markdown(f"#### {category} ({len(items)}건)")

        if not items:
            st.caption("찾은 내용이 없습니다.")
            continue

        for idx, item in enumerate(items):
            page = item.get("페이지")
            page_label = f"{page}페이지" if page else "페이지 미상"
            with st.container(border=True):
                st.markdown(f"**{item.get('항목','(항목 없음)')}**  ·  📄 {page_label}")
                st.write(item.get("내용", ""))

                # 원본 페이지 이미지 보기 (펼치기)
                if page:
                    with st.expander(f"🔍 원본 {page_label} 이미지 보기"):
                        try:
                            img = cached_page_image(
                                doc_data["pdf_path"], page, item.get("내용", "")
                            )
                            st.image(img, use_container_width=True)
                        except Exception as e:
                            st.caption(f"이미지를 만들지 못했습니다: {e}")


def render_step3():
    st.header("3단계: 금융조건 찾기")

    has_contract = "contract" in st.session_state
    has_im = "im" in st.session_state

    if not (has_contract and has_im):
        st.info(
            "먼저 **1단계(계약서)**와 **2단계(제안서)** 탭에서 두 문서를 모두 올려주세요. "
            "둘 다 준비되면 여기서 분석할 수 있습니다."
        )
        return

    api_key = get_api_key()
    if not api_key:
        st.error(
            "Anthropic(클로드) API 키가 설정되지 않았습니다. "
            "`.streamlit/secrets.toml` 파일에 `anthropic_api_key` 를 넣어주세요. "
            "(설정 방법은 담당자 안내 참고)"
        )
        return

    st.write("아래 버튼을 누르면 두 문서를 LLM으로 분석해 핵심 내용을 찾습니다. (수십 초 걸릴 수 있어요)")

    if st.button("🔎 금융조건 찾기 실행", type="primary", key="run_step3"):
        with st.spinner("계약서 분석 중..."):
            st.session_state["findings_contract"] = analyze_financial(
                st.session_state["contract"]["pages"], "계약서", api_key
            )
        with st.spinner("제안서 분석 중..."):
            st.session_state["findings_im"] = analyze_financial(
                st.session_state["im"]["pages"], "제안서", api_key
            )
        st.success("분석 완료!")

    # 분석 결과가 있으면 좌우 분할로 표시
    if "findings_contract" in st.session_state and "findings_im" in st.session_state:
        st.divider()
        left, right = st.columns(2)
        with left:
            render_findings_column(
                "계약서",
                st.session_state["contract"],
                st.session_state["findings_contract"],
                ["금융조건"],
            )
        with right:
            render_findings_column(
                "제안서",
                st.session_state["im"],
                st.session_state["findings_im"],
                ["금융조건"],
            )


def _render_comparison(header, contract_key, im_key, comp_key,
                       verify_prefix, btn_key, not_ready_msg):
    """
    4단계·6단계 공용 비교 화면.
    contract_key/im_key : 비교할 '찾은 내용'이 담긴 session_state 키
    comp_key            : 비교 결과를 저장할 session_state 키
    verify_prefix       : 확인 체크박스 키 접두사(단계마다 달라야 함)
    """
    st.header(header)

    if not (contract_key in st.session_state and im_key in st.session_state):
        st.info(not_ready_msg)
        return

    api_key = get_api_key()
    if not api_key:
        st.error("Anthropic(클로드) API 키가 설정되지 않았습니다.")
        return

    st.write("계약서를 기준으로 제안서를 항목별로 비교하고, 수정 방향을 정리합니다.")

    if st.button("📊 비교·정리 실행", type="primary", key=btn_key):
        with st.spinner("두 문서를 비교하는 중..."):
            st.session_state[comp_key] = compare_findings(
                st.session_state[contract_key],
                st.session_state[im_key],
                api_key,
            )
        st.success("비교 완료!")

    comparison = st.session_state.get(comp_key)
    if not comparison:
        return

    rows = comparison.rows

    # ── 항목별 비교표 (이미지 보기 + 확인 체크) ──────────
    st.subheader("📋 항목별 비교표")
    st.caption(
        "각 칸의 '🔍 원본 보기'를 누르면 그 내용이 있는 원본 페이지 이미지를 볼 수 있어요. "
        "직접 확인했고 맞으면 왼쪽 **확인** 칸을 체크하세요. (체크한 항목은 안 봐도 되는 것)"
    )

    # 확인 완료 개수 표시
    checked = sum(
        1 for i in range(len(rows))
        if st.session_state.get(f"{verify_prefix}{i}", False)
    )
    st.progress(
        (checked / len(rows)) if rows else 0.0,
        text=f"확인 완료: {checked} / {len(rows)} 항목",
    )

    # 표 머리글
    head = st.columns([0.6, 1.5, 2.8, 2.8, 1])
    head[0].markdown("**확인**")
    head[1].markdown("**항목**")
    head[2].markdown("**계약서**")
    head[3].markdown("**제안서**")
    head[4].markdown("**일치 여부**")

    for i, r in enumerate(rows):
        with st.container(border=True):
            c = st.columns([0.6, 1.5, 2.8, 2.8, 1])

            # ① 확인 체크박스 (체크 상태는 자동 저장됨)
            c[0].checkbox(
                "확인", key=f"{verify_prefix}{i}", label_visibility="collapsed"
            )

            # ② 항목 이름 + 그룹
            c[1].markdown(f"**{r.item}**  \n`{r.category}`")

            # ③ 계약서 내용 + 페이지번호 + 이미지 보기
            with c[2]:
                pg = f" `({r.contract_page}p)`" if r.contract_page else ""
                st.markdown((r.contract_value or "_(없음)_") + pg)
                if r.contract_page:
                    with st.expander(f"🔍 계약서 {r.contract_page}p 원본 보기"):
                        try:
                            img = cached_page_image(
                                st.session_state["contract"]["pdf_path"],
                                r.contract_page,
                                r.contract_value,
                            )
                            st.image(img, use_container_width=True)
                        except Exception as e:
                            st.caption(f"이미지 오류: {e}")

            # ④ 제안서 내용 + 페이지번호 + 이미지 보기
            with c[3]:
                pg = f" `({r.im_page}p)`" if r.im_page else ""
                st.markdown((r.im_value or "_(없음)_") + pg)
                if r.im_page:
                    with st.expander(f"🔍 제안서 {r.im_page}p 원본 보기"):
                        try:
                            img = cached_page_image(
                                st.session_state["im"]["pdf_path"],
                                r.im_page,
                                r.im_value,
                            )
                            st.image(img, use_container_width=True)
                        except Exception as e:
                            st.caption(f"이미지 오류: {e}")

            # ⑤ 일치 여부
            badge = {
                "일치": "🟢 일치",
                "차이": "🔴 차이",
                "계약서에만 있음": "🟠 계약서에만",
                "제안서에만 있음": "🟡 제안서에만",
            }.get(r.status, r.status)
            c[4].markdown(badge)

            # 차이 설명(수정방향) — 일치가 아닌 항목만 표 안에 바로 표시
            if r.status != "일치" and r.fix_instruction:
                st.caption(f"💬 차이/수정: {r.fix_instruction}")

    # ── 차이/누락 항목만 모은 수정 지시 ───────────
    st.subheader("✏️ 제안서 수정 사항 (계약서에 맞추기)")
    diffs = [r for r in rows if r.status != "일치"]
    if not diffs:
        st.success("차이나는 항목이 없습니다. 제안서가 계약서와 일치합니다.")
    else:
        for r in diffs:
            with st.container(border=True):
                pgc = f" ({r.contract_page}p)" if r.contract_page else ""
                pgi = f" ({r.im_page}p)" if r.im_page else ""
                st.markdown(f"**[{r.category}] {r.item}**  ·  상태: `{r.status}`")
                c1, c2 = st.columns(2)
                c1.markdown(f"📄 **계약서**{pgc}\n\n{r.contract_value or '(없음)'}")
                c2.markdown(f"📑 **제안서**{pgi}\n\n{r.im_value or '(없음)'}")
                if r.fix_instruction:
                    st.info(f"➡️ **수정 방향:** {r.fix_instruction}")

    # ── 총평 ─────────────────────────────────
    st.subheader("📝 총평")
    st.write(comparison.summary)


def render_step4():
    _render_comparison(
        header="4단계: 금융조건 비교·정리 (계약서 기준)",
        contract_key="findings_contract",
        im_key="findings_im",
        comp_key="comparison",
        verify_prefix="v4_",
        btn_key="run_step4",
        not_ready_msg="먼저 **🔎 3단계**에서 '금융조건 찾기 실행'을 눌러주세요. "
        "그 결과로 여기서 비교합니다.",
    )


def render_step6():
    _render_comparison(
        header="6단계: 권리·통제 구조 비교·정리 (계약서 기준)",
        contract_key="rights_contract",
        im_key="rights_im",
        comp_key="comparison_rights",
        verify_prefix="v6_",
        btn_key="run_step6",
        not_ready_msg="먼저 **🔐 5단계**에서 '권리·통제 구조 찾기 실행'을 눌러주세요. "
        "그 결과로 여기서 비교합니다.",
    )


def render_step5():
    st.header("5단계: 권리·통제 구조 찾기")
    st.caption(
        "선행/후행/채권보전 반영, 의사결정 권한, 담보 실행, 기한이익상실(EOD)을 찾습니다."
    )

    has_contract = "contract" in st.session_state
    has_im = "im" in st.session_state
    if not (has_contract and has_im):
        st.info(
            "먼저 **1단계(계약서)**와 **2단계(제안서)** 탭에서 두 문서를 모두 올려주세요. "
            "둘 다 준비되면 여기서 분석할 수 있습니다."
        )
        return

    api_key = get_api_key()
    if not api_key:
        st.error("Anthropic(클로드) API 키가 설정되지 않았습니다.")
        return

    st.write("아래 버튼을 누르면 두 문서에서 권리·통제 구조 항목을 찾습니다. (수십 초 걸릴 수 있어요)")

    if st.button("🔎 권리·통제 구조 찾기 실행", type="primary", key="run_step5"):
        with st.spinner("계약서 분석 중..."):
            st.session_state["rights_contract"] = analyze_rights(
                st.session_state["contract"]["pages"], "계약서", api_key
            )
        with st.spinner("제안서 분석 중..."):
            st.session_state["rights_im"] = analyze_rights(
                st.session_state["im"]["pages"], "제안서", api_key
            )
        st.success("분석 완료!")

    # 결과가 있으면 좌우 분할(4개 그룹)로 표시
    if "rights_contract" in st.session_state and "rights_im" in st.session_state:
        st.divider()
        left, right = st.columns(2)
        with left:
            render_findings_column(
                "계약서",
                st.session_state["contract"],
                st.session_state["rights_contract"],
                RIGHTS_GROUPS,
            )
        with right:
            render_findings_column(
                "제안서",
                st.session_state["im"],
                st.session_state["rights_im"],
                RIGHTS_GROUPS,
            )


# ─────────────────────────────────────────────
# "비교" 화면: 큰 구분 3개(버튼으로 넘길 수 있게) + 각 안에 하위 탭
#   1) 원본 읽기   2) 금융조건 검토   3) 권리·통제 구조 검토
# (기능은 그대로. 원본 텍스트는 session_state로 공유됨)
# ─────────────────────────────────────────────
BIG_SECTIONS = ["📄 원본 읽기", "💰 금융조건 검토", "🔐 권리·통제 구조 검토"]

# 각 구분의 하위 탭 라벨
SUB_READ = ["1) 계약서 읽기", "2) 제안서(IM) 읽기"]
SUB_FIN = ["핵심내용 찾기", "비교·정리"]
SUB_RIGHTS = ["핵심내용 찾기", "비교·정리"]

# 6단계 선형 순서: (구분, 하위탭 키, 하위탭 값, 다음버튼 표시이름)
LINEAR = [
    (BIG_SECTIONS[0], "sub_read", SUB_READ[0], "계약서 읽기"),
    (BIG_SECTIONS[0], "sub_read", SUB_READ[1], "제안서 읽기"),
    (BIG_SECTIONS[1], "sub_fin", SUB_FIN[0], "금융조건 찾기"),
    (BIG_SECTIONS[1], "sub_fin", SUB_FIN[1], "금융조건 비교"),
    (BIG_SECTIONS[2], "sub_rights", SUB_RIGHTS[0], "권리·통제 찾기"),
    (BIG_SECTIONS[2], "sub_rights", SUB_RIGHTS[1], "권리·통제 비교"),
]


def _current_linear_index():
    """지금 화면이 6단계 순서 중 몇 번째인지 계산."""
    sec = st.session_state.get("section", BIG_SECTIONS[0])
    for i, (s, sk, sv, _) in enumerate(LINEAR):
        if s == sec and st.session_state.get(sk) == sv:
            return i
    for i, (s, _, _, _) in enumerate(LINEAR):  # 못 찾으면 그 구분의 첫 단계
        if s == sec:
            return i
    return 0


def goto_linear(delta):
    """이전/다음 버튼 콜백: 6단계 순서로 한 칸 이동(구분+하위탭 동시 설정)."""
    j = max(0, min(len(LINEAR) - 1, _current_linear_index() + delta))
    sec, sk, sv, _ = LINEAR[j]
    st.session_state["section"] = sec
    st.session_state[sk] = sv


def _subtabs(key, options):
    """하위 탭도 '탭 모양'으로 그려주고 선택값 반환."""
    with st.container(key="subtabs"):
        return st.radio(
            "하위 선택", options, key=key,
            horizontal=True, label_visibility="collapsed",
        )


def render_compare():
    # 기본값 세팅
    st.session_state.setdefault("section", BIG_SECTIONS[0])
    st.session_state.setdefault("sub_read", SUB_READ[0])
    st.session_state.setdefault("sub_fin", SUB_FIN[0])
    st.session_state.setdefault("sub_rights", SUB_RIGHTS[0])

    # 라디오를 CSS로 '탭 모양'으로 (동그라미 숨김 + 선택 밑줄) — 큰 탭·하위 탭 공용
    st.markdown(
        """
        <style>
        .st-key-bigtabs div[role="radiogroup"],
        .st-key-subtabs div[role="radiogroup"]{
            flex-direction:row; gap:4px; border-bottom:2px solid #e6e6e6;
        }
        .st-key-bigtabs div[role="radiogroup"] label,
        .st-key-subtabs div[role="radiogroup"] label{
            margin:0; padding:8px 18px; cursor:pointer; font-weight:600;
            color:#666; border-bottom:3px solid transparent;
        }
        .st-key-bigtabs div[role="radiogroup"] label>div:first-child,
        .st-key-subtabs div[role="radiogroup"] label>div:first-child{ display:none; }
        .st-key-bigtabs div[role="radiogroup"] label:has(input:checked),
        .st-key-subtabs div[role="radiogroup"] label:has(input:checked){
            color:#ff4b4b; border-bottom:3px solid #ff4b4b;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # 문서 준비 상태
    has_contract = "contract" in st.session_state
    has_im = "im" in st.session_state
    st.caption(
        f"문서 준비 상태 — 계약서 {'✅' if has_contract else '⏳'}  ·  "
        f"제안서 {'✅' if has_im else '⏳'}"
    )

    # 큰 탭 줄 (구분 3개)
    with st.container(key="bigtabs"):
        st.radio(
            "구분 선택", BIG_SECTIONS, key="section",
            horizontal=True, label_visibility="collapsed",
        )

    sec = st.session_state["section"]

    # 선택된 구분의 하위 탭 + 내용
    if sec == BIG_SECTIONS[0]:
        sub = _subtabs("sub_read", SUB_READ)
        if sub == SUB_READ[0]:
            render_document_section("계약서", "contract")
        else:
            render_document_section("제안서", "im")
    elif sec == BIG_SECTIONS[1]:
        sub = _subtabs("sub_fin", SUB_FIN)
        if sub == SUB_FIN[0]:
            render_step3()
        else:
            render_step4()
    else:
        sub = _subtabs("sub_rights", SUB_RIGHTS)
        if sub == SUB_RIGHTS[0]:
            render_step5()
        else:
            render_step6()

    # 하단 이전/다음 버튼 (6단계 순서) + 초기화(다음 버튼 바로 옆)
    st.divider()
    idx = _current_linear_index()
    prev_col, _mid, reset_col, next_col = st.columns([1.4, 1.2, 1, 1.4])
    if idx > 0:
        prev_col.button(
            f"◀ 이전: {LINEAR[idx - 1][3]}",
            on_click=goto_linear, args=(-1,),
            use_container_width=True,
        )
    reset_col.button(
        "🔄 초기화",
        on_click=reset_all,
        use_container_width=True,
        help="올린 문서와 분석 결과를 모두 지우고 처음부터 다시 시작합니다.",
    )
    if idx < len(LINEAR) - 1:
        next_col.button(
            f"다음: {LINEAR[idx + 1][3]} ▶",
            on_click=goto_linear, args=(1,),
            type="primary", use_container_width=True,
        )


# ─────────────────────────────────────────────
# "메모" 화면: 제목/문제점/추가의견 입력 → 파일에 저장(껐다 켜도 유지)
# ─────────────────────────────────────────────
def render_memo():
    st.header("📝 메모")
    st.caption("사업별 문제점·의견을 적어 저장해두는 공간입니다. (파일에 저장되어 유지)")

    # 새 메모 입력 (제출하면 자동으로 칸 비움)
    with st.form("memo_form", clear_on_submit=True):
        title = st.text_input("제목(사업명)")
        problem = st.text_area("문제점")
        opinion = st.text_area("추가의견")
        submitted = st.form_submit_button("➕ 새 메모 추가", type="primary")

    if submitted:
        if not (title.strip() or problem.strip() or opinion.strip()):
            st.warning("내용을 한 가지 이상 입력해 주세요.")
        else:
            memos = load_memos()
            memos.append(
                {
                    "id": uuid.uuid4().hex,
                    "제목": title.strip(),
                    "문제점": problem.strip(),
                    "추가의견": opinion.strip(),
                }
            )
            save_memos(memos)
            st.success("메모를 저장했습니다.")

    st.divider()
    st.subheader("저장된 메모")

    memos = load_memos()
    if not memos:
        st.info("저장된 메모가 없습니다")
        return

    # 최신 메모가 위로 오게 역순 표시
    for m in reversed(memos):
        with st.container(border=True):
            top, btn = st.columns([5, 1])
            top.markdown(f"### {m.get('제목') or '(제목 없음)'}")
            if btn.button("🗑 삭제", key=f"del_{m['id']}"):
                remaining = [x for x in load_memos() if x["id"] != m["id"]]
                save_memos(remaining)
                st.rerun()
            if m.get("문제점"):
                st.markdown(f"**문제점**\n\n{m['문제점']}")
            if m.get("추가의견"):
                st.markdown(f"**추가의견**\n\n{m['추가의견']}")


# ─────────────────────────────────────────────
# 선택된 메뉴 화면 그리기 (메뉴는 위에서 이미 선택함)
# ─────────────────────────────────────────────
if menu == "비교":
    render_compare()
else:
    render_memo()
