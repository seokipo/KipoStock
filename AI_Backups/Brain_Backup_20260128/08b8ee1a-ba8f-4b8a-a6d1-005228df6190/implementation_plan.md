# V4.0 Upgrade: Color Logs & Report Stability

Upgrade the system to V4.0 with improved visual feedback and stability.

## User Review Required

> [!NOTE]
> The log color will follow the strategy color: 🔴 Red (Qty), 🟢 Green (Amt), 🔵 Blue (Pct).
> The default log color remains Green/Lime where not specific to a trade.

## Proposed Changes

### [Component] Trade Logging & Report Fix
- **[MODIFY] [trade_logger.py](file:///d:/Work/Python/AutoBuy/KipoBuy_Gui_3.알람/KipoBuy_Gui/trade_logger.py)**
    - Standardize all P&L keys to `pnl_amt` (instead of `pl_amt`) to fix the `KeyError` in the report generation.
- **[MODIFY] [chat_command.py](file:///d:/Work/Python/AutoBuy/KipoBuy_Gui_3.알람/KipoBuy_Gui/chat_command.py)**
    - Ensure the report drawing logic correctly references the standardized keys.

### [Component] UI Enhancements (Color Logs)
- **[MODIFY] [Kipo_GUI_main.py](file:///d:/Work/Python/AutoBuy/KipoBuy_Gui_3.알람/KipoBuy_Gui/Kipo_GUI_main.py)**
    - Update version to `V4.0`.
    - Adjust `append_log` to allow overriding the default text color (currently locked to `#00ff00`).
- **[MODIFY] [check_n_buy_1ju.py](file:///d:/Work/Python/AutoBuy/KipoBuy_Gui_3.알람/KipoBuy_Gui/check_n_buy_1ju.py)**
    - Calculate strategy color based on `seq`.
    - Wrap success log messages in `<font color='...'>` tags so they appear colored in the GUI.
- **[MODIFY] [check_n_sell.py](file:///d:/Work/Python/AutoBuy/KipoBuy_Gui_3.알람/KipoBuy_Gui/check_n_sell.py)**
    - Implement similar color-coding for sell order logs.

### [Component] Build Process
- **[NEW] [build_v4.0.py](file:///d:/Work/Python/AutoBuy/KipoBuy_Gui_3.알람/KipoBuy_Gui/build_v4.0.py)**
    - Create a new build script targeting `KipoStock_V4.0_FINAL.exe`.

## Verification Plan

### Automated Tests
- Run `REPORT` command after multiple trades to ensure `pnl_amt` error is resolved.
- Verify log output colors match the strategy used for each trade.

### Manual Verification
- Confirm version `V4.0` is displayed in the window title.
- Verify build success and exe functionality.
