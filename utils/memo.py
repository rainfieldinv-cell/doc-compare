"""
메모를 파일(memo.json)에 저장하고 불러오는 기능.
앱을 껐다 켜거나 브라우저를 새로고침해도 메모가 남아있게 합니다.
"""

import json
import os

# memo.json 은 프로젝트 폴더(이 파일의 한 단계 위)에 저장
MEMO_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "memo.json",
)


def load_memos() -> list:
    """저장된 메모 목록을 불러옵니다. 없으면 빈 목록."""
    if not os.path.exists(MEMO_FILE):
        return []
    try:
        with open(MEMO_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_memos(memos: list) -> None:
    """메모 목록을 파일에 저장합니다."""
    with open(MEMO_FILE, "w", encoding="utf-8") as f:
        json.dump(memos, f, ensure_ascii=False, indent=2)
