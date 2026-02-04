#!/bin/bash
# EC2 배포 스크립트 (Docker 사용)
# PostgreSQL은 docker-compose.yml에 포함되어 있어 별도 설치 불필요

set -e

echo "🚀 Starting deployment..."

# 기존 앱 컨테이너만 중지 및 제거 (PostgreSQL 데이터는 유지)
echo "📦 Stopping and removing existing app containers..."
docker-compose stop app || true
docker-compose rm -f app || true

# 앱 이미지만 제거 (PostgreSQL 이미지는 유지)
echo "🗑️  Removing old app images..."
docker images | grep -E "text2sql.*app|text2sql-app" | awk '{print $3}' | xargs -r docker rmi -f || true

# 사용하지 않는 이미지 정리 (디스크 공간 절약, PostgreSQL 제외)
echo "🧹 Cleaning up unused images (excluding postgres)..."
docker image prune -f

# 새로 빌드 (앱만)
echo "🔨 Building new app image..."
docker-compose build --no-cache app

# 컨테이너 시작 (PostgreSQL은 이미 실행 중이면 재시작 안 함)
echo "▶️ Starting containers..."
docker-compose up -d

# PostgreSQL이 완전히 준비될 때까지 대기
echo "⏳ Waiting for PostgreSQL to be ready..."
sleep 10

# 헬스 체크 (재시도 로직 포함)
echo "🏥 Waiting for application to be ready..."
max_attempts=30
attempt=0
while [ $attempt -lt $max_attempts ]; do
  if curl -f http://localhost:8000/api/health 2>/dev/null; then
    echo "✅ Application is healthy!"
    exit 0
  fi
  attempt=$((attempt + 1))
  echo "Attempt $attempt/$max_attempts failed, retrying in 5 seconds..."
  sleep 5
done
echo "❌ Health check failed after $max_attempts attempts"
docker-compose logs app
exit 1

echo "✅ Deployment completed successfully!"

