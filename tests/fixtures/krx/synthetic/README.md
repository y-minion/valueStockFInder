# KRX 합성 응답

이 폴더의 파일은 문서에 적힌 형식을 보고 손으로 쓴 값이에요. 실제 KRX 응답이 아니에요.
필드 이름(ISU_CD, TDD_CLSPRC, ISU_SRT_CD, SECUGRP_NM 등)은 제3자 자료를 따른 것이라
`tools/record_fixtures.py krx`로 실제 응답을 녹화하기 전까지는 확인되지 않았어요.
녹화본은 `tests/fixtures/krx/recorded/`에 들어가요.

- `{stk,ksq}_bydd_trd_YYYYMMDD.json`: 일별매매정보 (2025-12-30, 2026-11-13)
- `{stk,ksq}_isu_base_info_20261113.json`: 종목기본정보 (보통주, 우선주, 부동산투자회사, 스팩 포함)
- `empty.json`: 휴장일 응답 `{"OutBlock_1": []}`
