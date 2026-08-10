#!/bin/bash
# Build and push multi-arch Docker images
# Usage: ./build-push.sh

set -e

# Configuration
REGISTRY="${REGISTRY:-ghcr.io}"
APP_NAME="${APP_NAME:-garmin-dash}"
IMAGE_NAME="${REGISTRY}/${APP_NAME}"
TAG="${TAG:-latest}"

# Architecture tags
PLATFORMS="linux/amd64,linux/arm64"

echo "📦 Building ${IMAGE_NAME}:${TAG}"
echo "   Platforms: ${PLATFORMS}"
echo "   Registry: ${REGISTRY}"
echo "   App: ${APP_NAME}"
echo "   Tag: ${TAG}"
echo

# Build and push
docker buildx build \
    --push \
    --platform ${PLATFORMS} \
    --build-arg REGISTRY=${REGISTRY} \
    --build-arg APP_NAME=${APP_NAME} \
    --build-arg SIGNAL_API_NAME=signal-messenger \
    -t ${IMAGE_NAME}:${TAG} \
    -t ${IMAGE_NAME}:latest \
    .

echo
echo "✅ Build and push complete!"
echo "📡 Image available at: ${IMAGE_NAME}:${TAG}"
echo
echo "Next: Pull on your Raspberry Pi"
echo "   docker pull ${IMAGE_NAME}:${TAG}"
echo "   docker compose -f docker-compose.prod.yml up -d"
