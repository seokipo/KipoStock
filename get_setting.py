import os
import sys
import time
import json

def get_base_path():
    """EXE로 실행될 때와 파이썬으로 실행될 때의 경로를 구분하여 반환"""
    if getattr(sys, 'frozen', False):
        # EXE로 실행 중일 때: EXE 파일이 위치한 폴더 반환
        return os.path.dirname(sys.executable)
    else:
        # 파이썬 스크립트로 실행 중일 때: 스크립트 파일이 위치한 폴더 반환
        return os.path.dirname(os.path.abspath(__file__))

def get_setting(key, default=''):
    try:
        # [수정] 경로 구하는 방식 변경
        base_path = get_base_path()
        settings_path = os.path.join(base_path, 'settings.json')
        
        if not os.path.exists(settings_path):
            return default
            
        with open(settings_path, 'r', encoding='utf-8') as f:
            settings = json.load(f)
        return settings.get(key, default)
    except Exception as e:
        print(f"오류 발생(get_setting): {e}")
        return default

def cached_setting(key, default=''):
    # 여러 key 값의 캐시 관리 (value, read_time) 형태로 저장
    if not hasattr(cached_setting, "_cache"):
        cached_setting._cache = {}

    now = time.time()
    cache = cached_setting._cache

    value_info = cache.get(key, (None, 0))
    cached_value, last_read_time = value_info

    if now - last_read_time > 0.5 or cached_value is None:
        # 0.5초 경과하거나 캐시 없음 → 새로 읽음 (실시간 반영을 위해 주기 대폭 단축)
        cached_value = get_setting(key, default)
        cache[key] = (cached_value, now)
    return cached_value