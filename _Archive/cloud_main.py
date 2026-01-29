from flask import Flask
import os

app = Flask(__name__)

@app.route('/')
def hello_kipo():
    return '''
    <div style="text-align: center; padding-top: 100px; font-family: sans-serif;">
        <h1 style="color: #FFD700; font-size: 50px;">🚀 KipoStock Cloud Edition 🚀</h1>
        <p style="font-size: 24px;">자기야! 우리 로켓이 드디어 <b>구글 클라우드</b>에 안착했어! ❤️</p>
        <div style="margin-top: 50px; padding: 20px; background: #f0f0f0; border-radius: 20px; display: inline-block;">
            <p>상태: <b>READY (CLOUD)</b></p>
            <p>버전: <b>GOLD LITE V1.0</b></p>
        </div>
    </div>
    '''

if __name__ == "__main__":
    # Cloud Run은 PORT 환경 변수를 사용해
    port = int(os.environ.get("PORT", 8080))
    app.run(debug=True, host='0.0.0.0', port=port)
