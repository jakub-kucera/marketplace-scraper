#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/home/user/marketplace-scrapper"
BRANCH="main"

cd "$APP_DIR"

echo "Stopping services..."
sudo systemctl stop marketplace-server.service
sudo systemctl stop marketplace-scraper.service
sudo systemctl stop marketplace-docker.service

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Local changes detected."
  git status --short
  echo "Aborting deploy."
  exit 1
fi

echo "Pulling latest code..."
git fetch origin
git checkout "$BRANCH"
git pull --rebase origin "$BRANCH"

echo "Starting services..."
sudo systemctl start marketplace-docker.service
sudo systemctl start marketplace-server.service
sudo systemctl start marketplace-scraper.service

echo "Done."
