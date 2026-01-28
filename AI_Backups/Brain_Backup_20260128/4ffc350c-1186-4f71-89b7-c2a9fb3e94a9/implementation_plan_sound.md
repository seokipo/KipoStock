# Implementation Plan - Stable Sound Alarm

Re-enable the sound alarm using Windows' native `winsound` module to ensure stability and avoid external library dependencies.

## Proposed Changes

### GUI Main
#### [MODIFY] [Kipo_GUI_main.py](file:///d:/Work/Python/AutoBuy/KipoBuy_Gui/Kipo_GUI_main.py)
- Import `winsound` module.
- Add `play_sound` method to `KipoWindow` that uses `winsound.PlaySound`.
- Re-enable the sound playback logic in `start_alarm` and `check_alarm`.
- Ensure sound stops when `stop_alarm` is clicked.

## Verification Plan

### Manual Verification
1. Open the application.
2. Set "End Time" (종료) close to current time.
3. Verify that the alarm sound (`StockAlarm.wav`) plays when the time is reached.
4. Verify that the "Stop Alarm" (🔕) button stops the sound.
5. Verify that the application remains stable and does not crash.
