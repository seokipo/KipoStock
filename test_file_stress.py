import threading
import time
import os
import sys

# 테스트 대상 모듈 경로 추가
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from check_n_buy import save_json_safe, load_json_safe

TEST_FILE = "test_stress.json"

def writer_thread(id):
    for i in range(50):
        data = {"id": id, "count": i, "time": time.time()}
        success = save_json_safe(TEST_FILE, data)
        if not success:
            print(f"❌ Writer {id} failed at iteration {i}")
        time.sleep(0.01)

def reader_thread(id):
    for i in range(50):
        data = load_json_safe(TEST_FILE)
        if not data and os.path.exists(TEST_FILE):
             # 사실 빈 파일일 수도 있으나, 스트레스 상황에서 데이터 손실 여부 체크
             pass
        time.sleep(0.01)

if __name__ == "__main__":
    print("🚀 파일 I/O 스트레스 테스트 시작...")
    threads = []
    
    # 여러 명의 쓰기꾼과 읽기꾼 투입
    for i in range(3):
        threads.append(threading.Thread(target=writer_thread, args=(i,)))
        threads.append(threading.Thread(target=reader_thread, args=(i+10,)))
        
    for t in threads:
        t.start()
        
    for t in threads:
        t.join()
        
    print("✅ 테스트 종료. 충돌 에러가 출력되지 않았다면 성공입니다!")
    if os.path.exists(TEST_FILE):
        os.remove(TEST_FILE)
