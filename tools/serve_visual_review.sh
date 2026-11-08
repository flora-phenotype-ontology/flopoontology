#!/usr/bin/env bash
# Serve only a prepared review packet and its attributed images, read-only.
# Usage: REVIEW_BIND=10.73.11.158 tools/serve_visual_review.sh local-corpora/visual-pilot-200
set -euo pipefail
data_dir=$(realpath "${1:?Pass the development audit directory}")
site_dir="$data_dir/review-site"
bind_address=${REVIEW_BIND:-127.0.0.1}
port=${REVIEW_PORT:-8780}
test -f "$data_dir/review.html"
mkdir -p "$site_dir"
cp "$data_dir/review.html" "$site_dir/index.html"
# Hard links keep the packet small while remaining inside the isolated container mount.
mkdir -p "$site_dir/images"
cp -al "$data_dir/images/." "$site_dir/images/"
if docker container inspect flopo-visual-review >/dev/null 2>&1; then
    docker rm -f flopo-visual-review >/dev/null
fi
docker run -d --name flopo-visual-review --restart unless-stopped \
    --read-only --tmpfs /var/cache/nginx --tmpfs /var/run \
    -p "$bind_address:$port:80" -v "$site_dir:/usr/share/nginx/html:ro" \
    nginx@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10
printf 'Review packet: http://%s:%s/\n' "$bind_address" "$port"
