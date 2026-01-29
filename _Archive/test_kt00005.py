import requests
import json
from config import host_url
from login import fn_au10001 as get_token

def test_kt00005():
    token = get_token()
    endpoint = '/api/dostk/acnt'
    url = host_url + endpoint
    
    headers = {
        'Content-Type': 'application/json;charset=UTF-8',
        'authorization': f'Bearer {token}',
        'api-id': 'kt00007',
    }
    
    params = {
        'dmst_stex_tp': 'KRX',
        'order_gb': '00', # 전체
        'ch_cnt_tp': '1', # 당일
        'qry_tp': '0'
    }
    
    print(f"Testing {url} with kt00005...")
    try:
        response = requests.post(url, headers=headers, json=params)
        print(f"Status: {response.status_code}")
        data = response.json()
        print(json.dumps(data, indent=4, ensure_ascii=False))
        
        if 'tdy_acc_diary' in data:
            print("✅ Success: kt00005 is Daily Trade Log")
        else:
            print("❌ Failure: tdy_acc_diary not in response")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_kt00005()
