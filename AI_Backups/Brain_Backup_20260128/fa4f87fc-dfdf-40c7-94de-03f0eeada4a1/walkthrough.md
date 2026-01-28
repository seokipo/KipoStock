# Walkthrough - `:today` Daily Trade Log & Excel Export

Added a new feature to retrieve and display the daily trading log, including the search condition name for each stock, and providing an option to export the data to Excel (CSV).

## Changes Made

### 1. API Integration (`ka10170`)
- Created [acc_diary.py](file:///d:/Work/Python/AutoBuy/KipoBuy4.0/acc_diary.py) to interface with the "당일매매일지조회" API.
- Handles parameters for today's trades and retrieves detailed buy/sell information.

### 2. Search Condition Persistence
- Modified [check_n_buy_1ju.py](file:///d:/Work/Python/AutoBuy/KipoBuy4.0/check_n_buy_1ju.py) to save the mapping between a stock and the search condition that triggered its purchase into `stock_conditions.json`.
- This ensures that the trade log can show which condition search found each stock, even after multiple program restarts.

### 3. `:today` Command Implementation
- Added the `:today` command to [chat_command.py](file:///d:/Work/Python/AutoBuy/KipoBuy4.0/chat_command.py).
- **Log Display**: Generates a formatted table in the log window showing:
    - [조건식] 종목명
    - 매수 평균가 / 수량 / 총액
    - 매도 평균가 / 수량 / 총액
    - 손익 금액 및 수익률
- **Excel Export**: Automatically saves the data to a CSV file (e.g., `trade_log_20260122.csv`) in the program directory. This file can be opened directly in Excel with correct Korean encoding (UTF-8-SIG).

## How to Use

1. **Check Log**: Type `:today` in the command input box.
2. **View Table**: The trade log will appear in the log window with horizontal lines and aligned columns for easy reading.
3. **Open Excel**: Locate the `trade_log_YYYYMMDD.csv` file in your project folder to view the details in Excel.
4. **Help**: Type `help` to see the updated command list.

## UI Refinements & Fixes

- **Diary Fix (today command)**: broadened the search parameter to include all trade types (`ottks_tp='0'`) to ensure today's trades appear correctly in the log.
- **Alarm Fix**: Normalized time comparisons to handle formats like "9:50" (auto-padding to "09:50"), ensuring the alarm triggers correctly even if the leading zero is omitted.
- **Internal Fix**: Resolved a critical "os not defined" error that was preventing the system from saving stock-condition mappings.
- **Silent Settings**: Saving settings no longer prints the full `[조건식 목록]` to the log, keeping the console cleaner.
- **Off-Market Auto-Start**: If you click **START** during off-market hours, the system enters a **WAITING** state and will automatically start monitoring at 09:00 (or your set start time).
- **today Command**: Removed the `:` prefix. You can now just type `today`.
- **Startup Display**: The last saved search condition name is now correctly displayed on the left panel upon application startup.
- **UI Cleanup**:
    - Restored the **"Save Settings"** button.
    - Brightened the **log timestamp color** for better visibility.
    - Removed the redundant "[ 현재 선택된 조건식 ]" header.
    - Minimized margins and spacing for a more compact and professional look.
- **Icon Fix**:
    - Restored the application icon using Windows-specific `AppUserModelID` logic.
    - Bundled `icon.ico` directly into the executable data for robust loading.

## Executable Build Result

- **Executable Path**: [KipoStock_V4.0_GOLD.exe](file:///d:/Work/Python/AutoBuy/KipoBuy4.0/dist/KipoStock_V4.0_GOLD.exe)
- **Folder**: [dist folder](file:///d:/Work/Python/AutoBuy/KipoBuy4.0/dist/)
- **Note**: Always run from the `dist` folder to ensure all assets are loaded.

## Verification Results

- [x] today command handles inputs without colon.
- [x] Last saved condition name shows on startup.
- [x] UI margins and headers are refined.
- [x] App icon is correctly displayed.
- [x] Final executable built and verified.
