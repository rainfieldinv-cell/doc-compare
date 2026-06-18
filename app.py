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

import streamlit as st

from utils.analyze import (
    RIGHTS_GROUPS,
    analyze_financial,
    analyze_rights,
    compare_findings,
)
from utils.auth import require_password
from utils.loader import process_uploaded_document
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


# ─────────────────────────────────────────────
# 화면 기본 설정
# ─────────────────────────────────────────────
st.set_page_config(page_title="계약서·제안서 비교 도구", layout="wide")

# 🔒 비밀번호 확인 (맞아야 아래 화면이 보임)
require_password()

st.title("📑 계약서·제안서(IM) 비교 도구")
st.caption("1·2단계: 계약서 / 제안서 텍스트 추출")

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
# 화면 구성: 큰 탭 3개 + 각 안에 하위 탭
#   1) 원본 읽기   2) 금융조건 검토   3) 권리·통제 구조 검토
# (기능은 그대로, 배치만 묶음. 원본 텍스트는 session_state로 공유됨)
# ─────────────────────────────────────────────

# 두 문서 준비 상태 한눈에
has_contract = "contract" in st.session_state
has_im = "im" in st.session_state
st.caption(
    f"문서 준비 상태 — 계약서 {'✅' if has_contract else '⏳'}  ·  "
    f"제안서 {'✅' if has_im else '⏳'}"
)

tab_read, tab_fin, tab_rights = st.tabs(
    ["📄 원본 읽기", "💰 금융조건 검토", "🔐 권리·통제 구조 검토"]
)

# 1) 원본 읽기 — 계약서/제안서 읽기
with tab_read:
    read_contract, read_im = st.tabs(["1) 계약서 읽기", "2) 제안서(IM) 읽기"])
    with read_contract:
        render_document_section("계약서", "contract")
    with read_im:
        render_document_section("제안서", "im")

# 2) 금융조건 검토 — 핵심내용 찾기 / 비교·정리
with tab_fin:
    fin_find, fin_compare = st.tabs(["핵심내용 찾기", "비교·정리"])
    with fin_find:
        render_step3()
    with fin_compare:
        render_step4()

# 3) 권리·통제 구조 검토 — 핵심내용 찾기 / 비교·정리
with tab_rights:
    rights_find, rights_compare = st.tabs(["핵심내용 찾기", "비교·정리"])
    with rights_find:
        render_step5()
    with rights_compare:
        render_step6()
