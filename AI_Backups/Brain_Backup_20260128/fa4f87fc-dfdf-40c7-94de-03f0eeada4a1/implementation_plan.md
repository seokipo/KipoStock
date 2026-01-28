# Implementation Plan - `:today` Daily Trade Log

Add a new command `:today` that displays a formatted daily trade log in the system's log window, including the search condition name associated with each stock.

## Proposed Changes

### [Component: API]

#### [NEW] [acc_diary.py](file:///d:/Work/Python/AutoBuy/KipoBuy4.0/acc_diary.py)
Create a new module to handle the "당일매매일지조회" API call.
- Use `api-id: 'ka10170'`.
- Endpoint: `/api/dostk/acnt`.
- Return the `tdy_acc_diary` list and totals (`tdy_acc_diary_tot`).
- Parameters: `base_dt`, `ottks_tp`, `ch_crd_tp`.

### [Component: Storage]

#### [MODIFY] [check_n_buy_1ju.py](file:///d:/Work/Python/AutoBuy/KipoBuy4.0/check_n_buy_1ju.py)
- When a stock is successfully bought, save the mapping `stk_cd -> seq_name` to `stock_conditions.json`.

### [Component: Commands]

#### [MODIFY] [chat_command.py](file:///d:/Work/Python/AutoBuy/KipoBuy4.0/chat_command.py)
- Import `fn_kt00005` from `acc_diary.py`.
- Add `:today` command handling in `process_command`.
- Implement `today()` method:
    - Fetch API data.
    - Load `stock_conditions.json`.
    - Format a table with columns: `[조건식] 종목명`, `매수(평균,수량,금액)`, `매도(평균,수량,금액)`, `세금`, `손익`, `수익률`.
    - Print the formatted table with horizontal lines in the log window.
    - **[NEW]** Use `pandas` to save the data as a `.csv` file (e.g., `trade_log_20260122.csv`) and notify the user of the file path. This file can be opened directly in Excel.

## UI Refinements & Fixes

### [Component: Commands]
- Change `:today` to `today` in `chat_command.py`.
- Update help message to reflect the change.

### [Component: GUI]
- **Display Condition on Start**: Ensure `refresh_condition_list_ui` is called correctly after settings and condition list are loaded.
- **Refine Layout**:
    - Remove `[ 현재 선택된 조건식 ]` header from `rt_list`.
    - Minimize margins and spacing in `rt_layout`, `settings_layout`, and `strat_vbox`.
- **Icon Fix**:
    - Update `KipoWindow` to search for `icon.ico` as well as `icon.png`.
    - Ensure `icon.ico` is properly linked to the window icon.

### [Component: Build]
- Re-run `build_v4.0_FINAL.py` once changes are verified.

## Verification Plan

### Automated Tests
- Run `acc_diary.py` directly to verify API response structure.
- Run `test_today_cmd.py` (to be created) to verify formatting logic without actual API call (using mock data).

### Manual Verification
1. Start the program.
2. Input `:today` in the command box.
3. Verify the output appears in the log window with the correct columns and formatting.
4. Verify that bought stocks show their correct search condition name.
