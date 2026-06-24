# Contributing to ThinkParse

Thank you for your interest in contributing to ThinkParse! This document provides guidelines and instructions for contributing.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Development Workflow](#development-workflow)
- [Code Style](#code-style)
- [Testing](#testing)
- [Submitting Changes](#submitting-changes)
- [Documentation](#documentation)

## Code of Conduct

This project adheres to a Code of Conduct that all contributors are expected to follow. Please read [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) before contributing.

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/wzdavid/ThinkParse.git`
3. Create a branch: `git checkout -b feature/your-feature-name`
4. Make your changes
5. Test your changes
6. Submit a pull request

## Development Setup

### Prerequisites

- Python 3.10 or higher
- Docker and Docker Compose (for running services)
- Redis (can be run via Docker Compose)

### Local Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/wzdavid/ThinkParse.git
   cd ThinkParse
   ```

2. **Create a virtual environment**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   # Install API dependencies
   pip install -r api/requirements.txt
   pip install -r worker/requirements.txt
   pip install -r cleanup/requirements.txt
   ```

4. **Set up environment variables**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

5. **Start Redis (if not using Docker)**
   ```bash
   docker compose up -d redis
   # Or install and run Redis locally
   ```

## Development Workflow

### Branch Naming

- `feature/` - New features
- `fix/` - Bug fixes
- `docs/` - Documentation changes
- `refactor/` - Code refactoring
- `test/` - Test additions or changes
- `chore/` - Maintenance tasks

### Commit Messages

We follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, etc.)
- `refactor`: Code refactoring
- `test`: Test additions or changes
- `chore`: Maintenance tasks

**Examples:**
```
feat(api): add task cancellation endpoint
fix(worker): handle memory errors gracefully
docs(readme): update installation instructions
```

## Code Style

### Python Style Guide

- Follow PEP 8 style guide
- Use type hints for all function signatures
- Use `typing` module for complex types
- Use `Optional[T]` for nullable values
- Use `Union[T, U]` for multiple types

**Example:**
```python
from typing import Optional, Dict, Any

def process_task(
    task_id: str,
    options: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    ...
```

### Code Organization

- Keep functions small and focused
- Use descriptive variable and function names
- Add docstrings to all public functions and classes
- Follow PEP 8 style guide

## Submitting Changes

### Pull Request Process

1. **Update your branch**
   ```bash
   git checkout main
   git pull upstream main
   git checkout your-branch
   git rebase main
   ```

2. **Review your changes**
   - Ensure code follows PEP 8 style guide
   - Check that all functions have proper type hints
   - Verify that docstrings are present for public functions

3. **Update documentation** if needed

4. **Create a Pull Request**
   - Provide a clear description of changes
   - Reference any related issues
   - Include screenshots for UI changes
   - Ensure CI checks pass

### PR Checklist

- [ ] Code follows the style guidelines
- [ ] Documentation updated (if needed)
- [ ] Commit messages follow conventions
- [ ] No merge conflicts
- [ ] CI checks pass

## Documentation

### Code Documentation

- Use docstrings for all public functions, classes, and modules
- Follow Google or NumPy docstring style
- Include parameter descriptions and return types
- Add examples for complex functions

**Example:**
```python
def submit_task(
    file: UploadFile,
    backend: str = "pipeline",
    lang: str = "ch"
) -> Dict[str, Any]:
    """
    Submit a document parsing task to the queue.
    
    Args:
        file: The document file to parse (PDF, image, etc.)
        backend: Processing backend ('pipeline', 'vlm-transformers', etc.)
        lang: Language code ('ch', 'en', etc.)
    
    Returns:
        Dictionary containing task_id and status
    
    Raises:
        HTTPException: If task submission fails
    """
    ...
```

### README Updates

- Keep README.md and README.zh.md in sync
- Update examples when API changes
- Document breaking changes in CHANGELOG.md

## Questions?

If you have questions, please:
- Open an issue for bug reports or feature requests
- Start a discussion for general questions
- Contact maintainers for security issues (see SECURITY.md)

Thank you for contributing to ThinkParse! 🎉
