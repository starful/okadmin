"""Instagram card-news brand profile (site-agnostic).

One shared prompt for the OK Japan Instagram account.
Primary: Japanese food, cuts, menu words, ordering.
Secondary: dining manners, transport (travel context only).
"""
from __future__ import annotations

import re
from typing import Any


def strip_slide_copy(text: str) -> str:
    """Card slide Korean copy: no sentence-ending punctuation on images."""
    s = (text or "").strip()
    s = re.sub(r"\.\s+", " ", s)
    return re.sub(r"[.?!…]+$", "", s).strip()

# Single Instagram brand — not tied to okramen/okonsen/etc.
INSTAGRAM_PROFILE: dict[str, Any] = {
    "theme": "일본 먹거리·메뉴·부위·주문 (야키니쿠·야키토리·해산물·라멘·스시)",
    "audience": "일본 여행을 준비하거나 식당 메뉴판 앞에서 헷갈리는 한국인",
    "hashtags": [
        "#일본여행",
        "#일본먹거리",
        "#야키니쿠",
        "#이자카야",
        "#일본메뉴",
        "#여행카드뉴스",
    ],
    # Generation priority: food/cuts first; etiquette/transport secondary.
    "categories": (
        "food, cuts, menu, order, yakiniku, yakitori, seafood, ramen, sushi, "
        "izakaya, etiquette, transport"
    ),
}

# Hub site tab: still shown on Japan-tourism sites (same global queue).
INSTAGRAM_ENABLED_SITES = frozenset({
    "okramen",
    "okonsen",
    "okcaddie",
    "jpcampus",
})


def is_instagram_enabled(site_id: str) -> bool:
    return (site_id or "").strip() in INSTAGRAM_ENABLED_SITES


def site_profile(_site_id: str | None = None) -> dict[str, Any]:
    """Compatibility shim — always the shared Instagram profile."""
    return dict(INSTAGRAM_PROFILE)


def site_public_url(_site_id: str | None = None) -> str:
    """No per-site CTA on Instagram cards."""
    return ""


def instagram_common_rules() -> str:
    p = INSTAGRAM_PROFILE
    return f"""일본 먹거리 인스타 카드뉴스 이미지를 만들어줘.

[브랜드]
- 테마: {p['theme']}
- 독자: {p['audience']}
- 계정: OK - JAPAN (사이트 URL을 넣지 말 것)

[주제 우선순위]
1) 메인: 먹거리·부위·메뉴 단어·주문법 (야키니쿠/야키토리/해산물/라멘/스시/이자카야)
2) 서브: 식당 매너·교통 (여행 맥락이 필요할 때만). 골프·온천·유학·채용 등 다른 세로 금지.

[필수]
1) 총 7장만 만든다. (1장 표지 + 2~6장 포인트 5개 + 7장 마무리)
2) 한 장의 출력 이미지 = 카드뉴스 1장만. 격자/콜라주/여러 장 합치기 금지.
3) 비율·크기: Instagram 세로 4:5만 사용. 정확히 1080×1350 픽셀. 1:1·9:16·스토리 비율 금지.
4) 배경: 순수 흰색(#FFFFFF)
5) 반드시 채팅에 첨부한 「OK - JAPAN」원형 로고(후지산·해·벚꽃)를 매 장 상단(좌 또는 우)에 작게 넣는다. 로고 없이 생성하지 말 것. 로고를 새로 그리지 말고 첨부 이미지를 그대로 사용.
6) 한글은 깨지지 않게 정확히. 읽기 쉬운 큰 글씨. 제목·부제·본문 끝에 마침표(.)·물음표·느낌표 넣지 말 것.
7) 보라색/네온/워터마크 금지. 색은 밝고 다양하게 (딥블루만 쓰지 말 것).
8) 여백이 휑하면 안 됨.
9) 7장 각각 하단 일러스트·배경 장면은 서로 달라야 함. 같은 인물·구도·배경·소품 반복 금지.
10) 주제는 먹거리·부위·메뉴·주문 위주. 매너·교통은 보조로만.
11) 7장(마무리)에는 저장·공유 유도만. 웹사이트 URL·도메인 주소를 넣지 말 것.

[레이아웃]
상단 30%: 로고 + 번호(해당 시) + 제목
중단 25%: 본문 2~3줄
하단 45%: 주제 관련 큰 일러스트/아이콘 장면으로 채움
텍스트만 있는 슬라이드 금지. 플랫 벡터, 귀엽고 선명한 일러스트.
7장 마무리: 저장 유도 (URL 없음)

지금 1장(표지)부터 시작해. 한 이미지에 한 장만 출력해. 모든 장은 4:5 (1080×1350).
확인 질문 하지 말고, 장마다 이미지를 이어서 만들어.
"""


def common_rules_for_site(_site_id: str | None = None) -> str:
    """Compatibility shim — always the shared Instagram rules."""
    return instagram_common_rules()


def suggest_topics_from_md(_site_id: str, *, limit: int = 12) -> list[dict[str, Any]]:
    """MD suggestions disabled — Instagram is not tied to site content repos."""
    return []
