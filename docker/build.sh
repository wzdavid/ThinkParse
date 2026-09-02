#!/bin/sh
# Build script for MinerU Docker images
# This script ensures base images are built before dependent images

set -e

# Get the directory where the script is located
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Get project root directory (parent of docker/)
PROJECT_ROOT="$(cd .. && pwd)"

echo "=== MinerU Docker Build Script ==="
echo "Project root: $PROJECT_ROOT"
echo ""

# Parse command line arguments
BUILD_ALL=false
BUILD_API=false
BUILD_WORKER_GPU=false
BUILD_WORKER_CPU=false
BUILD_CLEANUP=false
REBUILD_BASE=false

while [ "$#" -gt 0 ]; do
    case $1 in
        --all|-a)
            BUILD_ALL=true
            shift
            ;;
        --api)
            BUILD_API=true
            shift
            ;;
        --worker-gpu|--gpu)
            BUILD_WORKER_GPU=true
            shift
            ;;
        --worker-cpu|--cpu)
            BUILD_WORKER_CPU=true
            shift
            ;;
        --cleanup)
            BUILD_CLEANUP=true
            shift
            ;;
        --rebuild-base)
            REBUILD_BASE=true
            BUILD_WORKER_GPU=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--all|--api|--worker-gpu|--worker-cpu|--cleanup|--rebuild-base]"
            exit 1
            ;;
    esac
done

# If no specific service is specified, try to read from COMPOSE_PROFILES
if [ "$BUILD_ALL" = false ] && [ "$BUILD_API" = false ] && [ "$BUILD_WORKER_GPU" = false ] && [ "$BUILD_WORKER_CPU" = false ] && [ "$BUILD_CLEANUP" = false ]; then
    # Try to read COMPOSE_PROFILES from docker/.env file
    if [ -f "$SCRIPT_DIR/.env" ]; then
        # Read COMPOSE_PROFILES from .env file
        # Handle both COMPOSE_PROFILES=value and COMPOSE_PROFILES="value" formats
        COMPOSE_PROFILES=$(grep "^COMPOSE_PROFILES=" "$SCRIPT_DIR/.env" 2>/dev/null | sed 's/^COMPOSE_PROFILES=//' | sed 's/^"//' | sed 's/"$//' | sed "s/^'//" | sed "s/'$//" | xargs || echo "")
        
        if [ -n "$COMPOSE_PROFILES" ]; then
            echo "Reading COMPOSE_PROFILES from docker/.env: $COMPOSE_PROFILES"
            echo ""
            
            # Check if COMPOSE_PROFILES contains mineru-cpu or mineru-gpu
            # Handle comma-separated values like "redis,mineru-cpu" or "redis,mineru-gpu"
            if echo "$COMPOSE_PROFILES" | grep -qE "(^|,)mineru-cpu(,|$)"; then
                BUILD_WORKER_CPU=true
                echo "✓ Auto-detected: Building CPU Worker (from COMPOSE_PROFILES)"
            elif echo "$COMPOSE_PROFILES" | grep -qE "(^|,)mineru-gpu(,|$)"; then
                BUILD_WORKER_GPU=true
                echo "✓ Auto-detected: Building GPU Worker (from COMPOSE_PROFILES)"
            fi
            
            # Always build API and Cleanup (they don't have profiles)
            BUILD_API=true
            BUILD_CLEANUP=true
            echo ""
        else
            # If COMPOSE_PROFILES is not set, build all
            echo "COMPOSE_PROFILES not found in docker/.env, building all services..."
            echo ""
            BUILD_ALL=true
        fi
    else
        # If .env file doesn't exist, build all
        echo "docker/.env file not found, building all services..."
        echo ""
        BUILD_ALL=true
    fi
fi

echo "Building services..."
echo ""

if [ "$BUILD_ALL" = true ] || [ "$BUILD_API" = true ]; then
    echo "Building mineru-api..."
    docker compose build mineru-api
    echo "✓ mineru-api built"
    echo ""
fi

if [ "$BUILD_ALL" = true ] || [ "$BUILD_WORKER_GPU" = true ]; then
    # Check if base image exists (only needed for GPU worker)
    if [ "$REBUILD_BASE" = true ] || ! docker image inspect mineru-vllm:latest > /dev/null 2>&1; then
        if [ "$REBUILD_BASE" = true ]; then
            echo "Forcing rebuild of base image 'mineru-vllm:latest'..."
        else
            echo "Base image 'mineru-vllm:latest' not found. Building it first..."
        fi
        echo ""
        echo "Building base image from Dockerfile.base..."
        cd "$PROJECT_ROOT"
        docker build -f docker/Dockerfile.base \
            --build-arg PIP_INDEX_URL=${PIP_INDEX_URL:-https://pypi.org/simple} \
            -t mineru-vllm:latest .
        echo ""
        echo "✓ Base image 'mineru-vllm:latest' built successfully"
        echo ""
        # Return to docker directory
        cd "$SCRIPT_DIR"
    else
        echo "✓ Base image 'mineru-vllm:latest' already exists"
        echo ""
    fi
    
    echo "Building mineru-worker-gpu (requires base image mineru-vllm:latest)..."
    docker compose build mineru-worker-gpu
    echo "✓ mineru-worker-gpu built"
    echo ""
fi

if [ "$BUILD_ALL" = true ] || [ "$BUILD_WORKER_CPU" = true ]; then
    echo "Building mineru-worker-cpu..."
    docker compose build mineru-worker-cpu
    echo "✓ mineru-worker-cpu built"
    echo ""
fi

if [ "$BUILD_ALL" = true ] || [ "$BUILD_CLEANUP" = true ]; then
    echo "Building mineru-cleanup..."
    docker compose build mineru-cleanup
    echo "✓ mineru-cleanup built"
    echo ""
fi

echo "=== Build Complete ==="
echo ""
echo "Built images:"
docker images | grep -E "mineru|REPOSITORY" | head -10
