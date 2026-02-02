import requests
import json
from config import host_url
from login import fn_au10001 as get_token

def debug_bal():
    token = get_token()
    endpoint = '/api/dostk/acnt'
    url =  host_url + endpoint

    headers = {
        'Content-Type': 'application/json;charset=UTF-8', 
        'authorization': f'Bearer {token}', 
        'api-id': 'kt00001', 
    }
    params = {'qry_tp': '3'}

    try:
        response = requests.post(url, headers=headers, json=params)
        print("Status:", response.status_code)
        data = response.json()
        print("Full Body:", json.dumps(data, indent=4, ensure_ascii=False))
    except Exception as e:
        print("Error:", e)

if __name__ == '__main__':
    debug_bal()
