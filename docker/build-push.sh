#!/bin/bash
# Build multi-arch image (amd64 + arm64) and push to a private registry.
# Usage: ./build-push.sh            (uses env: REGISTRY, APP_NAME, TAG, GHCR_USER, GHCR_TOKEN)
#   cd docker && ./build-push.sh
#   REGISTRY=ghcr.io APP_NAME=<github-user>/garmin-dash TAG=v0.2.0 ./build-push.sh
#
# Requirements on the dev machine:
#   - docker with buildx (docker buildx version)
#   - qemu/binfmt for cross-arch builds:
#       docker run --privileged --rm tonistiigi/binfmt --install all
#   - registry credentials (first time only):
#       docker login ghcr.io -u <github-user>   (paste a PAT with write:packages)

set -euo pipefail

cd "$(dirname "$0")/.."   # repo root = build context

REGISTRY="${REGISTRY:-ghcr.io}"
APP_NAME="${APP_NAME:-<your-github-user>/garmin-dash}"
TAG="${TAG:-latest}"
PLATFORMS="${PLATFORMS:-linux/amd64,linux/arm64}"
IMAGE="${REGISTRY}/${APP_NAME}"

echo "📦 ${IMAGE}:${TAG}  (${PLATFORMS})"
echo

# 1. Ensure a docker-container builder exists (needed for multi-platform --push)
if ! docker buildx inspect garmin-builder >/dev/null 2>&1; then
  echo "🔧 Creating buildx builder 'garmin-builder'..."
  docker buildx create --name garmin-builder --driver docker-container --use
else
  docker buildx use garmin-builder
fi

# 2. Optional login (GHCR_TOKEN can be a PAT with write:packages; omit for public repos)
if [[ -n "${GHCR_USER:-}" && -n "${GHCR_TOKEN:-}" ]]; then
  echo "🔑 Logging in to ${REGISTRY} as ${GHCR_USER}..."
  echo "${GHCR_TOKEN}" | docker login "${REGISTRY}" -u "${GHCR_USER}" --password-stdin
fi

# 3. Build + push
docker buildx build \
  --push \
  --platform "${PLATFORMS}" \
  -t "${IMAGE}:${TAG}" \
  -t "${IMAGE}:latest" \
  .

echo
echo "✅ Pushed ${IMAGE}:${TAG} (+ :latest)"
echo
echo "Next — on the Raspberry Pi:"
echo "   docker pull ${IMAGE}:${TAG}"
echo "   docker compose -f docker-compose.prod.yml up -d"
