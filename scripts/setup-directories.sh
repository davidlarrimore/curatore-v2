#!/usr/bin/env bash
# scripts/setup-directories.sh

set -euo pipefail

echo "📁 Setting up Curatore v2 directories..."

# Create required directories in project root
mkdir -p uploads
mkdir -p processed

# Set permissions (for Linux/macOS)
if [[ "$OSTYPE" != "msys" && "$OSTYPE" != "win32" ]]; then
    chmod 755 uploads
    chmod 755 processed
    echo "✅ Directory permissions set"
fi

# Create .gitkeep files to ensure directories are tracked
touch uploads/.gitkeep
touch processed/.gitkeep

echo "✅ Created directories:"
echo "   📂 ./uploads/ (for uploaded files)"
echo "   📂 ./processed/ (for processed documents)"

# Stop existing containers
echo "🛑 Stopping existing containers..."
docker-compose down || true

# Rebuild and restart
echo "🏗️ Rebuilding containers..."
docker-compose build

echo "🚀 Starting services..."
docker-compose up -d

echo "⏳ Waiting for services to start..."
sleep 10

echo "🔍 Checking directory mounts..."
docker exec curatore-backend ls -la /app/uploads || echo "⚠️ Upload directory not accessible in container"
docker exec curatore-backend ls -la /app/processed || echo "⚠️ Processed directory not accessible in container"

echo ""
echo "✅ Setup complete!"
echo "📁 Upload directory: $(pwd)/uploads"
echo "📁 Processed directory: $(pwd)/processed"
echo "🌐 Frontend: http://localhost:3000"
echo "🔗 Backend: http://localhost:8000"
echo ""
echo "Try uploading a file now - it should appear in the uploads folder!"