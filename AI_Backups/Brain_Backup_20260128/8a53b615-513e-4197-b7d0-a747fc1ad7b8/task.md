# Task: 자동 시퀀스 전환 안정화 및 UI 논리 개선

- [x] 프로그래밍 용어 사전 업데이트 (`Race Condition` 등)
- [x] `Kipo_GUI_main.py` 로직 수정
    - [x] `on_stop_clicked` 메서드 분리 및 리팩토링
    - [x] 매매 중(`RUNNING`) 자동 시퀀스 명령 차단 로직 구현
    - [x] 이전의 5초 지연 로직 제거
    - [x] `lock_ui_for_sequence`에서 `READY` 상태 시 잠금 해제 허용
    - [x] GUI 시퀀스 버튼과 원격 명령 간 정책 동기화
- [ ] `ChatCommand` 및 `AsyncWorker` 상태 동기화 (on_start, on_stop) [/]
- [ ] 시퀀스 모드 활성화 시 엔진 자동 시작 버그 수정 (V5.4.16) [/]
- [ ] 버전 업데이트 (V5.4.17) 및 빌드 [/]
- [ ] 최종 검증 및 워크쓰루 작성 [/]
