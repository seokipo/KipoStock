import os
import sys
import time
import json

def get_base_path():
    """사용자가 지정한 고정 데이터 경로를 최우선으로 반환"""
    # [v4.2.8] 사용자 요청에 따른 데이터 고정 경로 업데이트 (V1.0 제거)
    fixed_path = r"D:\Work\Python\AutoBuy\ExeFile\KipoStockAi"
    if os.path.exists(fixed_path):
        return fixed_path
        
    if getattr(sys, 'frozen', False):
        # EXE로 실행 중일 때: EXE 파일이 위치한 폴더 반환
        return os.path.dirname(sys.executable)
    else:
        # 파이썬 스크립트로 실행 중일 때: 스크립트 파일이 위치한 폴더 반환
        return os.path.dirname(os.path.abspath(__file__))

# 전역 캐시 변수 (파일 I/O 최소화)
_SETTINGS_CACHE = {}
_LAST_SETTINGS_LOAD_TIME = 0

def get_setting(key, default=''):
    global _SETTINGS_CACHE, _LAST_SETTINGS_LOAD_TIME
    try:
        now = time.time()
        # [최적화] 1초 이내 요청은 메모리 캐시 사용 (매 초 수백번의 I/O 방지)
        if _SETTINGS_CACHE and (now - _LAST_SETTINGS_LOAD_TIME < 1.0):
            return _SETTINGS_CACHE.get(key, default)

        base_path = get_base_path()
        settings_path = os.path.join(base_path, 'settings.json')
        
        if not os.path.exists(settings_path):
            return default
            
        with open(settings_path, 'r', encoding='utf-8') as f:
            _SETTINGS_CACHE = json.load(f)
            _LAST_SETTINGS_LOAD_TIME = now
            
        return _SETTINGS_CACHE.get(key, default)
    except Exception as e:
        # print(f"오류 발생(get_setting): {e}") # 로그 과다 방지
        return default

def cached_setting(key, default=''):
    """기존 인터페이스 유지를 위해 사용 (이제 get_setting 자체가 캐싱됨)"""
    return get_setting(key, default)

def clear_settings_cache():
    """[v6.8.8] 파일 저장 후 캐시를 강제로 비워 최신 정보를 즉시 리로드하도록 함"""
    global _SETTINGS_CACHE, _LAST_SETTINGS_LOAD_TIME
    _SETTINGS_CACHE = {}
    _LAST_SETTINGS_LOAD_TIME = 0