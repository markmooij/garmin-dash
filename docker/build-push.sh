#!/bin/bash
# Build multi-arch image (amd64 + arm64) and push to the private registry.
# Usage: ./build-push.sh                    (pushes ghcr.io/yourname/garmin-dash:latest)
#   cd docker && ./build-push.sh
#   TAG=v0.2.0 ./build-push.sh               (also tags/pushes a version tag)
#
# Requirements on the dev machine:
#   - docker with buildx (docker buildx version)
#   - qemu/binfmt for cross-arch builds:
#       docker run --privileged --rm tonistiigi/binfmt --install all
#   - push access to ghcr.io/yourname is already network/ACL-managed —
#     no `docker login` needed. If that ever changes, set REGISTRY_USER/
#     REGISTRY_TOKEN and this script will log in first.

set -euo pipefail

cd "$(dirname "$0")/.."   # repo root = build context

REGISTRY="${REGISTRY:-ghcr.io/yourname}"
APP_NAME="${APP_NAME:-garmin-dash}"
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

# 2. Optional login — only needed if REGISTRY_USER/REGISTRY_TOKEN are set.
#    ghcr.io/yourname access is already managed, so this is a no-op by default.
if [[ -n "${REGISTRY_USER:-}" && -n "${REGISTRY_TOKEN:-}" ]]; then
  echo "🔑 Logging in to ${REGISTRY} as ${REGISTRY_USER}..."
  echo "${REGISTRY_TOKEN}" | docker login "${REGISTRY}" -u "${REGISTRY_USER}" --password-stdin
fi

# 3. Build + push
TAGS=(-t "${IMAGE}:latest")
if [[ "${TAG}" != "latest" ]]; then
  TAGS+=(-t "${IMAGE}:${TAG}")
fi

docker buildx build \
  --push \
  --platform "${PLATFORMS}" \
  -f docker/Dockerfile \
  "${TAGS[@]}" \
  .

echo
echo "✅ Pushed ${IMAGE}:latest$( [[ "${TAG}" != "latest" ]] && echo " (+ :${TAG})" )"
echo
echo "Next — on the Raspberry Pi:"
echo "   docker compose -f docker-compose.prod.yml pull"
echo "   docker compose -f docker-compose.prod.yml up -d"
