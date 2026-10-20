#!/usr/bin/env sh
# Attach the demo pack to a GitHub release (build machine only; CI does not hold the dataset).
#   deploy/prod/release-pack.sh v1.0.0
set -eu
tag="$1"
cd "$(dirname "$0")/../.."
(cd backend && uv run verita demo pack --dataset hi_small --pack ../demo-pack \
  && uv run verita demo verify --pack ../demo-pack)
tar -czf "verita-demo-pack-$tag.tar.gz" demo-pack
sha256sum "verita-demo-pack-$tag.tar.gz" > "verita-demo-pack-$tag.tar.gz.sha256"
gh release upload "$tag" "verita-demo-pack-$tag.tar.gz" "verita-demo-pack-$tag.tar.gz.sha256"
