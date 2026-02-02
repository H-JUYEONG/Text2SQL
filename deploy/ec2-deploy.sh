#!/bin/bash
# EC2 배포 스크립트 (Docker 사용)

set -e

echo "🚀 Starting deployment..."

# 기존 컨테이너 중지 및 제거, 이미지도 제거
echo "📦 Stopping and removing existing containers and images..."
docker-compose down --rmi all || true

# 사용하지 않는 이미지 정리 (디스크 공간 절약)
echo "🧹 Cleaning up unused images..."
docker image prune -f

# 새로 빌드
echo "🔨 Building new image..."
docker-compose build --no-cache

# 컨테이너 시작
echo "▶️ Starting containers..."
docker-compose up -d

# 헬스 체크
echo "🏥 Health check..."
sleep 5
curl -f http://localhost:8000/api/health || exit 1

echo "✅ Deployment completed successfully!"

