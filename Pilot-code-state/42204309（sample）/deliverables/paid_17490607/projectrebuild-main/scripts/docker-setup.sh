#!/bin/bash
# Docker setup script for Project Rebuild

set -e

echo "🐳 Project Rebuild - Docker Setup"
echo "=================================="
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker Desktop."
    exit 1
fi

# Check if docker-compose is available
if ! command -v docker-compose &> /dev/null; then
    echo "❌ docker-compose is not installed."
    exit 1
fi

echo "✅ Docker is running"
echo ""

# Build images
echo "📦 Building Docker images..."
docker-compose build

echo ""
echo "✅ Setup complete!"
echo ""
echo "Quick start commands:"
echo "  npm run docker:node    - Start blockchain node"
echo "  npm run docker:test    - Run tests"
echo "  npm run docker:compile - Compile contracts"
echo "  npm run docker:shell   - Open dev shell"
echo ""
echo "For more information, see docs/docker.md"

