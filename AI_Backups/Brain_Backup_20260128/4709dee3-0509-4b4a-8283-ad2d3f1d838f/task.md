# Task: Finalize v4.2 Enhancements

- [x] Planning Fixes
    - [x] Create implementation plan
- [x] Implementing Fixes
    - [x] Add more tax field candidates in `chat_command.py`
    - [x] Implement sorting by condition name in `today` method
    - [x] Optimize `today` speed using `asyncio.gather` and `requests.Session`
    - [x] Add `clr` command to guide and implement GUI logic
    - [x] Fix `AttributeError` in 장외 시간 reservation logic
    - [x] Restrict market hours to 09:00 - 15:30
    - [x] Implement auto-stop/today/report sequence at 15:30
    - [x] Handle Excel file open error with friendly message
    - [x] Restore Telegram chatbot command polling
- [x] Verifying Fixes
    - [x] Verify code changes
    - [x] (Manual) User verification
