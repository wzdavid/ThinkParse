#!/bin/bash
# ThinkParse Virtual Environment Setup Script
# 用于快速设置开发环境的虚拟环境

set -e  # Exit on error

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}🚀 ThinkParse Virtual Environment Setup${NC}"
echo ""

# Check Python version
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 10 ]); then
    echo -e "${RED}❌ Error: Python 3.10+ is required. Current version: $PYTHON_VERSION${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Python version: $PYTHON_VERSION${NC}"

# Virtual environment directory
VENV_DIR=".venv"

# Check if venv already exists
if [ -d "$VENV_DIR" ]; then
    echo -e "${YELLOW}⚠️  Virtual environment already exists at $VENV_DIR${NC}"
    read -p "Do you want to recreate it? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}🗑️  Removing existing virtual environment...${NC}"
        rm -rf "$VENV_DIR"
    else
        echo -e "${GREEN}✅ Using existing virtual environment${NC}"
        source "$VENV_DIR/bin/activate"
        echo -e "${GREEN}✅ Virtual environment activated${NC}"
        exit 0
    fi
fi

# Create virtual environment
echo -e "${GREEN}📦 Creating virtual environment...${NC}"
python3 -m venv "$VENV_DIR"

# Activate virtual environment
echo -e "${GREEN}🔌 Activating virtual environment...${NC}"
source "$VENV_DIR/bin/activate"

# Upgrade pip
echo -e "${GREEN}⬆️  Upgrading pip...${NC}"
pip install --upgrade pip setuptools wheel

# Install dependencies
echo -e "${GREEN}📥 Installing dependencies...${NC}"
echo ""

# Install API dependencies
echo -e "${YELLOW}📦 Installing API dependencies...${NC}"
pip install -r api/requirements.txt

# Install Worker dependencies
echo -e "${YELLOW}📦 Installing Worker dependencies...${NC}"
pip install -r worker/requirements.txt

# Install Cleanup dependencies (optional)
echo -e "${YELLOW}📦 Installing Cleanup dependencies...${NC}"
pip install -r cleanup/requirements.txt

# Summary
echo ""
echo -e "${GREEN}✅ Virtual environment setup complete!${NC}"
echo ""
echo -e "${GREEN}📝 Next steps:${NC}"
echo "  1. Activate the virtual environment:"
echo -e "     ${YELLOW}source .venv/bin/activate${NC}"
echo ""
echo "  2. Copy environment configuration:"
echo -e "     ${YELLOW}cp .env.example .env${NC}"
echo ""
echo "  3. Edit .env file with your configuration"
echo ""
echo "  4. Start Redis (required for Celery):"
echo -e "     ${YELLOW}# Using Docker:${NC}"
echo -e "     ${YELLOW}docker run -d -p 6379:6379 redis:latest${NC}"
echo ""
echo "  5. Run the API server:"
echo -e "     ${YELLOW}cd api && python app.py${NC}"
echo ""
echo "  6. Run the worker (in another terminal):"
echo -e "     ${YELLOW}cd worker && python tasks.py${NC}"
echo ""
echo -e "${GREEN}💡 Tip: Add 'source .venv/bin/activate' to your shell profile for auto-activation${NC}"
