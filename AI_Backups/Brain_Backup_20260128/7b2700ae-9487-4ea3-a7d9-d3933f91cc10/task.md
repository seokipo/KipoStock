# Sequence Auto Implementation

- [ ] UI Implementation
    - [x] Add 'Sequence Auto' checkbox (`chk_seq_auto`) to `Kipo_GUI_main.py`
    - [x] Persist checkbox state in `settings.json`
- [x] Logic Implementation (`Kipo_GUI_main.py`)
    - [x] Update `check_alarm` (or create `check_schedule`) to handle Start/End events.
    - [x] **Start Event**: Play short sound + `start` command.
    - [x] **End Event**:
        - [x] If `Seq Auto` OFF: Play Alarm + Continue Trading.
        - [x] If `Seq Auto` ON:
            - [x] Stop current alarm if any.
            - [x] Check next profile index (Current + 1).
            - [x] Load next profile settings (Start/End time, Conditions, etc.).
            - [x] Update GUI & Engine settings.
            - [x] Log transition.
            - [x] If last profile finished, Stop + Alarm.
- [x] Verification
    - [x] Test Seq Auto OFF (End time -> Alarm only, Running)
    - [x] Test Seq Auto ON (End time -> Switch Profile)

# Post-Implementation
- [x] UI Refinement (Save Icon, Sequence Blinking Button)
- [x] Preserve Settings (Sync `dist/settings.json` to root)
- [x] Rebuild Executable
- [x] Notify User

# Bug Fixes
- [x] Fix AttributeError: 'toggle_always_on_top'
- [x] Fix RuntimeError: lost sys.stdin (remove input() in exception)
- [x] Fix AttributeError: 'toggle_profile_blink'
- [x] Fix Crash on Profile Click (Restored missing methods)
- [x] UI Improvements (Larger Buttons, Profile Data Indicator)
- [x] UI Refinement: Increase Icon Size (Font size: 28px) for Save/Sequence buttons
- [x] Rebuild Executable
