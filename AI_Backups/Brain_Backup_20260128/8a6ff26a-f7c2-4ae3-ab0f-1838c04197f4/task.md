# Sequence & Automation Refinement (V5.2.4)

시퀀스 자동화의 안정성을 높이고, 특정 상황에서 발생하던 중복 로그인 및 버튼 비활성화 버그를 해결하였습니다.

- [x] [FIX] R10001 중복 로그인 방지 로직 고도화 (시퀀스 전환 딜레이 추가)
- [x] [FIX] START 버튼 먹통 현상 해결 (WAITING 상태 및 시퀀스 종료 시 상태 관리)
- [x] [CLEAN] today 리포트 및 로그에서 [DEBUG] 머리말 제거
- [x] [FEAT] today 리포트 전략별 색상 구분 (Qty:빨강, Amt:초록, Pct:파랑)
- [x] [REFINED] 시퀀스 자동 모드 안정성 강화 (프로필 로드 시 상태 유지 등)

# V5.2.5 Stability Fixes
- [x] [FIX] `_on_connection_closed` 재연결 간섭 방지 (is_starting 체크 강화)
- [x] [FIX] 시퀀스 전환 시 종료 알람 로그 개선 (종료 -> 전환으로 문구 수정)
- [x] [FIX] 시작/종료 시간 동일 설정 시 무한 루프 방지

# V5.2.6 Trade Data Fixes
- [x] [FIX] today 리포트 데이터 불일치(0원 표시) 해결 (ka10170/ka10077 데이터 병합 개선)
- [x] [FIX] 실현손익 계산 시 제세금 누락 보정

# V5.3.1 Final Accuracy & Branding
- [x] [FIX] today 리포트 '세금' 컬럼 누락 해결 및 정렬 최적화
- [x] [FIX] API 필드 매핑 보강 (Synonyms 대응으로 0원 표시 방지)
- [x] [FIX] 실행 파일명 변경 (KipoStock_V5.2_Automation.exe) 및 아이콘 적용

# V5.3.2 Summary Statistics
- [x] [NEW] today 리포트 하단 합계 행 추가 (매수/매도/세금/손익 총합)
- [x] [NEW] 수익률 평균값 계산 및 표시
- [x] [FIX] 구분선 추가로 가독성 개선

# V5.3.3 Final Build & Branding
- [x] [FIX] 빌드 시 파일 잠금 문제 해결 (사용자 안내 강화)
- [x] [FIX] 실행 파일명 고정: KipoStock_V5.3.3_Auto.exe
- [x] [FIX] 로그 헤더 및 합계 행 정렬 최종 검수

# V5.3.4 Icon & Stability
- [x] [FIX] 왼쪽 상단 및 작업표시줄 아이콘 복구 (Resource Bundling)
- [x] [FIX] 빌드 시 아이콘 파일 자동 복사 로직 추가

# V5.3.5 Telegram Command Enhancements (DONE)
- [x] [FIX] 텔레그램 `Clr` 명령어 인식 및 GUI 로그 초기화 연동
- [x] [FIX] 텔레그램 `Print` 명령어 오류 수정 (인자 체크 및 대소문자 구분 없음)
- [x] [FIX] 모든 명령어 앞뒤 공백 및 대소문자 허용 처리

# V5.3.6 Log Export Command (DONE)
- [x] [NEW] 텔레그램 `Log` 명령어 추가 (GUI 로그를 .txt 파일로 저장)
- [x] [NEW] 파일명 형식 준수: `Log_YYYYMMDD_y.txt` (y는 일렬번호)
- [x] [FIX] 추출 시 HTML 태그 제거 및 가독성 확보

# V5.3.7 Report Column Enhancement
- [x] [FIX] 리포트 내 `[매수전략]` 컬럼 추가 (매수시간과 조건식 사이)
- [x] [FIX] 전략명 매칭: `qty` → `1주`, `amount` → `금액`, `percent` → `비율`
- [x] [FIX] 정렬 및 가독성 최종 검수
