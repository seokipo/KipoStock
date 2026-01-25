# 📊 KipoStock 전체 시스템 흐름도 (Flowchart)

이 문서는 `KipoStock` 자동 매매 시스템의 전체적인 동작 흐름을 시각적으로 설명합니다.

## 1. 메인 프로세스 흐름

```mermaid
graph TD
    Start([프로그램 실행]) --> Init[설정 로드 및 GUI 초기화]
    Init --> Idle{대기 상태}
    
    Idle -- START 클릭 또는 자동시작 --> Login[토큰 발급 및 계좌 동기화]
    Login --> EngineStart[매수/매도 엔진 가동]
    
    subgraph "감시 루프 (Background)"
        EngineStart --> WS[WebSocket 실시간 감시 시작]
        EngineStart --> SellLoop[매도 체크 루프 시작]
        
        WS -- 종목 검출 / 실시간 신호 --> BuyCheck{매수 조건 체크}
        BuyCheck -- 조건 만족 --> BuyExe[매수 주문 실행]
        
        SellLoop -- 주기적 (0.1초) --> SellCheck{보유 종목 수익률 체크}
        SellCheck -- 익절/손절 범위 도달 --> SellExe[매도 주문 실행]
    end
    
    subgraph "자동 관리"
        Idle -- 장외 시간 --> Waiting[15:30 정산 및 대기 모드]
        Waiting -- 다음날 09:00 --> Login
    end
    
    Idle -- STOP 클릭 --> Stop[엔진 정지 및 리소스 정리]
    Stop --> Idle
```

## 2. 매수 로직 상세 (chk_n_buy)

```mermaid
flowchart TD
    Signal[검색 신호 수신] --> Exist{이미 보유 중인가?}
    Exist -- 예 --> Skip[무시]
    Exist -- 아니오 --> MaxStock{최대 종목 수 초과?}
    MaxStock -- 예 --> Skip
    MaxStock -- 아니오 --> Balance{예수금 충분한가?}
    Balance -- 아니오 --> Skip
    Balance -- 예 --> Strategy[매수 전략 적용]
    Strategy --> Qty[1주 고정]
    Strategy --> Amt[설정 금액]
    Strategy --> Pct[잔고 대비 비율]
    Qty & Amt & Pct --> Order[매수 주문 전송]
    Order --> Log[성공 시 로그 기록 및 알림]
```

## 3. 매도 로직 상세 (chk_n_sell)

```mermaid
flowchart TD
    Loop[0.1초마다 반복] --> GetHoldings[보유 종목 리스트 확인]
    GetHoldings --> EachStock{각 종목별 수익률 확인}
    EachStock -- "수익률 > 익절가" --> Sell[매도 실행]
    EachStock -- "수익률 < 손절가" --> Sell
    EachStock -- "범위 이내" --> Next[다음 종목 확인]
    Sell -- 성공 --> Notify[텔레그램 알림 및 세션 기록]
```

---
*이 플로우차트는 KipoStock V5.3.9 기준으로 작성되었습니다.*
