# 1. 파이썬 베이스 이미지 사용 (더 튼튼한 표준 이미지로 변경)
FROM python:3.10

# 2. 작업 디렉토리 설정
WORKDIR /app

# 3. 환경 변수 설정
ENV PYTHONUNBUFFERED=1

# 4. 종속성 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. 소스 코드 복사
COPY . .

# 6. 실행 명령
CMD ["python3", "cloud_engine_main.py"]
