# Walkthrough - Fix Persistent Alarm Crash

I have fixed the crash that occurred when the alarm time was reached.

## Changes Made

### GUI Main
#### [Kipo_GUI_main.py](file:///d:/Work/Python/AutoBuy/KipoBuy_Gui/Kipo_GUI_main.py)
1. **Initialized `last_alarm_time`**: Added `self.last_alarm_time = None` to prevent `AttributeError`.
2. **Removed Broken Code**: Deleted the orphaned `else:` block that caused `NameError`.
3. **Re-enabled Sound**: Integrated `winsound` for stable, non-blocking alarm playback on Windows.
4. **UI Cleanup**: 
    - Fixed duplicate "종료" 시간 input.
    - Reorganized "시작", "종료", "알람 버튼"의 배열을 깔끔하게 정리했습니다.
    - 배너 타이틀을 `V3.8.1 (Ultra)`로 업데이트하고 전반적인 UI 간격을 최적화했습니다.
5. **Visual Alarm Feedback**: 
    - 알람 발생 시 종 버튼(🔔)이 노란색과 빨간색으로 0.5초 간격으로 깜빡거리도록 시각 효과를 추가했습니다.
    - 소리 파일이 없거나 음소거 상태여도 알람 상태를 쉽게 인지할 수 있습니다.

render_diffs(file:///d:/Work/Python/AutoBuy/KipoBuy_Gui/Kipo_GUI_main.py)

## Verification Results

### Code Review
- The `AttributeError` and `NameError` are resolved.
- UI elements are now correctly aligned without duplicates.
- The alarm button color blinks between yellow and red when active.
- `blink_timer` reliably cycles the button's stylesheet.

### Build Status
- **Success**: The final build was successful.
- **Location**: `dist/KipoStock_GUI_V3.8.1_ULTRA.exe`

> [!IMPORTANT]
> 만약 .exe 파일을 실행 중이시라면, 변경된 코드를 반영하기 위해 **다시 빌드(Build)**해야 합니다. 
> `build_exe.py`를 실행하여 새로운 실행 파일을 만들어 주세요.
