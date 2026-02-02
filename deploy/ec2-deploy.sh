#!/bin/bash
# EC2 배포 스크립트 (Docker 사용)

set -e

echo "🚀 Starting deployment..."

# Docker 컨테이너 중지 및 제거
echo "📦 Stopping existing containers..."
docker-compose down || true

# 최신 이미지 pull (또는 빌드)
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

