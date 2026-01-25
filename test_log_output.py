import sys
import os

# Add current directory to path so we can import the modules
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

from check_n_buy_1ju import chk_n_buy, ACCOUNT_CACHE

def mock_buy_stock(stk_cd, qty, price_type, token=None):
    return '0', '성공'

# Patch buy_stock
import check_n_buy_1ju
check_n_buy_1ju.buy_stock = mock_buy_stock
check_n_buy_1ju.get_current_price = lambda code, token: (None, 5000)

print("--- Testing Log Output ---")
# Mock data
stk_cd = "005930" # Samsung
ACCOUNT_CACHE['balance'] = 1000000
ACCOUNT_CACHE['holdings'] = set()
ACCOUNT_CACHE['names'][stk_cd] = "삼성전자"

# Call chk_n_buy with seq_name
chk_n_buy(stk_cd, token="mock_token", seq="1", trade_price=5000, seq_name="급당주 돌파")

print("\n--- Test Finished ---")
