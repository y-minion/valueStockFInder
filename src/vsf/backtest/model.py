"""백테스트 판정 묶음의 모양 (2026-11-24 백테스트 설계 4장)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Verdict:
    """한 규칙(기준값)에서 본 계산기 판정. 주가와 무관한 값만 담아요."""
    gate1: str
    gate2: str
    fair: float | None        # 보수적 적정가 B105 (숫자일 때만)
    buy_line: float | None    # 매수선 B107
    method: str | None        # 적정가를 정한 방법 B106
    uncomputable: bool        # B105 == "계산 불가" (정상 EPS 0 이하)

    def cheap_ok(self) -> bool:
        """주가만 매수선 이하로 내려오면 살 수 있는 판정: 관문 ①② 탈락 없음, 적정가·매수선이 숫자."""
        return (self.gate1 != "탈락" and self.gate2 != "탈락"
                and self.fair is not None and self.buy_line is not None)


@dataclass(frozen=True)
class Vintage:
    """회사×사업연도 판정 묶음. 그 사업보고서의 원본 공시일 다음 첫 거래일(valid_from)부터 써요."""
    code: str
    corp_code: str
    name: str
    common_code: str | None
    year: int                 # 사업연도 L
    filed: date               # 원본 공시일
    valid_from: date          # 공시일 다음 첫 거래일 (공시일 당일은 빼요)
    shares: float | None      # valid_from 날 상장주식수
    dps: float | None         # L년 DPS (우선주면 우선주 DPS), valid_from 주식 수 기준
    substitute: bool          # 금융회사 대체 자료로 만듦
    verdicts: dict[str, Verdict]
    blocked: bool = False     # 연말 뒤 주식 수가 크게 바뀌어 주당 숫자를 믿기 어려움: 이 묶음으로는 사지 않아요
