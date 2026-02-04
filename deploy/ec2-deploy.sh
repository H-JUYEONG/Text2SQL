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

# 헬스 체크
echo "🏥 Health check..."
sleep 5
curl -f http://localhost:8000/api/health || exit 1

echo "✅ Deployment completed successfully!"

