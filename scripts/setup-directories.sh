#!/usr/bin/env bash
# scripts/setup-directories.sh
set -euo pipefail

echo "🔧 Setting up Curatore v2 directory structure..."

# Create the single files directory structure at root level
mkdir -p files/uploaded_files
mkdir -p files/processed_files
mkdir -p files/batch_files

# Create .gitkeep files to preserve directory structure in git
touch files/uploaded_files/.gitkeep
touch files/processed_files/.gitkeep
touch files/batch_files/.gitkeep

# Remove any old backend-level files directories if they exist
if [ -d "backend/files" ]; then
    echo "🗑️  Removing old backend/files directory..."
    rm -rf backend/files
fi

# Set permissions (optional, for Unix systems)
chmod 755 files
chmod 755 files/uploaded_files
chmod 755 files/processed_files
chmod 755 files/batch_files

echo "✅ Directory structure created:"
echo "   📁 files/"
echo "   ├── 📁 uploaded_files/    (for user uploads)"
echo "   ├── 📁 processed_files/   (for processed markdown)"
echo "   └── 📁 batch_files/       (for local batch processing)"
echo ""
echo "🐳 You can now run: docker-compose up --build"