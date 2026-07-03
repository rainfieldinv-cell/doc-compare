"""
간단한 비밀번호 잠금 기능.

비밀번호는 .streamlit/secrets.toml 의 app_password 값과 비교합니다.
비밀번호가 맞을 때까지 나머지 화면을 보여주지 않습니다.
"""

import streamlit as st


def require_password():
    """
    비밀번호가 맞으면 True를 반환하고 화면을 계속 진행합니다.
    틀리거나 아직 입력 안 했으면 입력창만 보여주고 멈춥니다.
    """
    # 비밀번호 제거: 통합 대시보드에서만 접근을 통제하므로 이 도구는 잠금 없이 통과합니다.
    # (다시 잠그려면 아래 'return True' 한 줄만 지우면 원래대로 동작합니다.)
    return True

    # 이미 로그인했으면 통과
    if st.session_state.get("authenticated"):
        return True

    # secrets.toml 에서 정답 비밀번호 읽기
    correct = st.secrets.get("app_password", None)
    if not correct:
        st.error(
            "비밀번호가 설정되어 있지 않습니다. "
            ".streamlit/secrets.toml 파일에 app_password 를 넣어주세요."
        )
        st.stop()

    # 비밀번호 입력창
    st.title("🔒 로그인")
    st.caption("회사 내부용 도구입니다. 비밀번호를 입력하세요.")

    # 폼으로 묶으면 입력칸에서 '엔터'만 쳐도 제출됩니다.
    with st.form("login_form"):
        password = st.text_input("비밀번호", type="password")
        submitted = st.form_submit_button("로그인")

    if submitted:
        if password == correct:
            st.session_state["authenticated"] = True
            st.rerun()  # 화면을 새로 그려서 본 화면으로 진입
        else:
            st.error("비밀번호가 틀렸습니다.")

    # 로그인 전에는 여기서 멈춰서 아래 내용이 안 보이게 함
    st.stop()
