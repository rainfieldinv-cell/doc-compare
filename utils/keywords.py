"""
구글 시트에 정리한 '검토 키워드' 를 읽어오는 부품.

시트 구조(사장님이 만든 형태):
  1행: 제목("키워드") - 병합된 제목 줄
  2행: 계약서 종류 이름들 (열마다 하나씩: 대출약정서, 사모사채인수계약서 ...)
  3행부터: 각 계약서(열) 아래로 검토 키워드를 한 줄에 하나씩

시트를 "링크가 있는 모든 사용자 - 뷰어" 로 공유해두면
로그인 없이 export CSV 로 통째로 읽을 수 있습니다.
"""

import csv
import io
import re
import urllib.request


def _parse_sheet_id_gid(sheet_url: str):
    """공유 링크에서 시트 ID 와 gid(탭 번호)를 뽑아냅니다."""
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9\-_]+)", sheet_url)
    if not m:
        raise ValueError("구글 시트 주소 형식이 아닙니다. (…/spreadsheets/d/… 형태여야 함)")
    sheet_id = m.group(1)
    g = re.search(r"[#?&]gid=(\d+)", sheet_url)
    gid = g.group(1) if g else "0"
    return sheet_id, gid


def _csv_export_url(sheet_url: str) -> str:
    sheet_id, gid = _parse_sheet_id_gid(sheet_url)
    return (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}"
        f"/export?format=csv&gid={gid}"
    )


def _fetch_csv(url: str, timeout: int = 15) -> str:
    """CSV 원문을 통째로 내려받습니다."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_keywords_csv(text: str) -> dict:
    """
    CSV 텍스트를 파싱해서
      {
        "all": [키워드, ...],                  # 전체(중복 제거, 순서 유지)
        "by_contract": {계약서명: [키워드,...]}  # 계약서(열)별
      }
    로 돌려줍니다.
    """
    rows = list(csv.reader(io.StringIO(text)))
    # 완전히 빈 행 제거하지 않고 그대로 두되, 셀은 공백 정리
    rows = [[(c or "").strip() for c in r] for r in rows]
    rows = [r for r in rows if any(r)]  # 통째로 빈 줄만 제거
    if not rows:
        return {"all": [], "by_contract": {}}

    # 1행이 '제목 한 칸'이면(비어있는 칸 빼고 1개 이하) 제목으로 보고 건너뜀 → 다음 행이 계약서명
    def non_empty_count(r):
        return sum(1 for c in r if c)

    header_idx = 0
    if len(rows) >= 2 and non_empty_count(rows[0]) <= 1 and non_empty_count(rows[1]) >= 1:
        header_idx = 1  # 1행은 "키워드" 제목 → 2행이 계약서명 헤더

    header = rows[header_idx]
    body = rows[header_idx + 1:]

    by_contract = {}
    all_keywords = []
    seen = set()
    n_cols = max((len(r) for r in rows), default=0)

    for col in range(n_cols):
        contract = header[col].strip() if col < len(header) else ""
        col_name = contract or "(미분류)"
        col_keywords = []
        for r in body:
            if col < len(r) and r[col]:
                kw = r[col]
                col_keywords.append(kw)
                if kw not in seen:
                    seen.add(kw)
                    all_keywords.append(kw)
        if col_keywords:
            # 같은 이름 열이 여러 개면 합침
            by_contract.setdefault(col_name, [])
            by_contract[col_name].extend(col_keywords)

    return {"all": all_keywords, "by_contract": by_contract}


def load_keywords(sheet_url: str) -> dict:
    """
    공유 링크(sheet_url)를 받아 시트를 읽고 키워드를 정리해 돌려줍니다.
    실패하면 예외를 던지므로, 호출부에서 try/except 로 감싸 안내하세요.
    """
    url = _csv_export_url(sheet_url)
    text = _fetch_csv(url)
    # 로그인 페이지(HTML)가 내려오면 공유가 안 된 것
    head = text.lstrip()[:15].lower()
    if head.startswith("<!doctype") or head.startswith("<html"):
        raise PermissionError(
            "시트를 읽지 못했습니다. 공유를 '링크가 있는 모든 사용자 - 뷰어' 로 바꿔주세요."
        )
    return parse_keywords_csv(text)
