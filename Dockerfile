FROM python:3.10-slim
WORKDIR /app
# 의존성 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# .env와 모든 소스 복사
COPY . . 
ENV PORT=8080
ENV LOCAL_DEV_AUTH=0
CMD ["python", "admin_server.py"]