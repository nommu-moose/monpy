# Build and Distribution Strategy

This document explains how the monpy package is built and distributed with code obfuscation and Cython compilation.

## Overview

The package uses a **two-layer protection strategy**:

1. **Obfuscation**: All Python source code is obfuscated using `py-obfuscate`
2. **Compilation**: Obfuscated code is compiled to native binaries using Cython

## What Users Get

### When Installing from Pre-built Wheels (Most Users)

```bash
pip install monpy
```

Users receive:
- ✅ **Binary files only**: `.pyd` (Windows) or `.so` (Linux/macOS)
- ✅ **Package structure**: `__init__.py` files only (required for Python packages)
- ✅ **No source code**: No `.py` files with actual logic
- ✅ **Fast installation**: No compilation needed

**Example installed structure:**
```
site-packages/monpy/
├── __init__.py                 # Package marker (minimal)
├── client.pyd                  # Compiled binary (Windows)
├── exceptions.pyd              # Compiled binary
├── helpers/
│   ├── __init__.py            # Package marker
│   ├── upsert_item.pyd        # Compiled binary
│   └── webhook.pyd            # Compiled binary
└── oo/
    ├── __init__.py            # Package marker
    ├── board.pyd              # Compiled binary
    └── item.pyd               # Compiled binary
```

### When Building from Source (No Matching Wheel)

If no pre-built wheel matches the user's platform:

1. pip downloads the source distribution (`.tar.gz`)
2. Source contains **obfuscated** `.py` files
3. Cython compiles them during installation
4. Final result: same as pre-built wheels (binaries only)

## Build Process

### Automated via GitHub Actions

The build workflow (`.github/workflows/build-and-publish.yml`) creates distributions for:

- **Windows**: x64
- **Linux**: x64 (manylinux)
- **macOS**: x64 and ARM64 (M1/M2)
- **Python versions**: 3.10, 3.11, 3.12

### Build Steps

1. **Obfuscation** (`prepare-source` job)
   - Copies source code
   - Runs `py-obfuscate` to remove docstrings and rename variables
   - Creates obfuscated source artifact

2. **Wheel Building** (`build-wheels` job)
   - Runs on Windows, Linux, and macOS runners
   - Uses `cibuildwheel` to build wheels for all Python versions
   - Compiles obfuscated `.py` → binary `.pyd/.so`
   - Custom `setup.py` excludes `.py` files from wheels (keeps only `__init__.py`)
   - Verifies wheel contents

3. **Source Distribution** (`build-sdist` job)
   - Creates `.tar.gz` with obfuscated source
   - Used as fallback when no wheel matches

4. **Publishing** (`publish` job)
   - Collects all wheels and sdist
   - Pushes to binary distribution repository

## Local Development

### Building Wheels Locally

```bash
# Install build dependencies
pip install cibuildwheel cython setuptools py-obfuscate

# Build wheels for current platform
python -m cibuildwheel --output-dir wheelhouse
```

### Verifying Wheel Contents

Use the provided verification script:

```bash
python scripts/verify_wheel.py wheelhouse/
```

This will check that:
- ✅ Only `__init__.py` files exist as `.py`
- ✅ Binary files (`.pyd`/`.so`) are present
- ❌ No source `.py` files are included

### Manual Build Steps

```bash
# 1. Obfuscate source (optional for testing)
cp -r src/ obfuscated_src/
py-obfuscate --in-place --remove-docstrings obfuscated_src/

# 2. Build wheel
pip install build cython
python -m build --wheel

# 3. Verify
python scripts/verify_wheel.py dist/
```

## Configuration Files

### `setup.py`

- Finds all `.py` files except `__init__.py`
- Creates Cython extensions for each file
- Custom `BuildPyExcludeCythonized` class excludes `.py` source from wheels
- Only `__init__.py` files remain in final package

### `pyproject.toml`

```toml
[tool.setuptools.package-data]
monpy = ["**/*.pyd", "**/*.so", "**/__init__.py", "py.typed"]

[tool.setuptools.exclude-package-data]
monpy = ["**/*.py", "**/*.pyc", "**/*.pyo"]
```

- Explicitly includes binary files and `__init__.py`
- Excludes all other `.py` files from the wheel

### `MANIFEST.in`

Controls what goes into the source distribution:
- Includes all necessary build files
- Includes all `.py` files (obfuscated in build process)
- Excludes build artifacts

## Security Considerations

### What This Protects Against

- ✅ **Casual code inspection**: No readable source in installed package
- ✅ **Simple reverse engineering**: Obfuscated + compiled
- ✅ **Direct code copying**: Binary format prevents easy copying

### What This Does NOT Protect Against

- ❌ **Determined reverse engineering**: Binaries can be decompiled
- ❌ **Runtime inspection**: Python objects can be introspected
- ❌ **Memory dumps**: Code visible in memory when running

**Note**: This is **obfuscation**, not encryption. It raises the bar but doesn't make reverse engineering impossible.

## Troubleshooting

### Users Report "No matching distribution found"

- Check that wheels were built for all target platforms
- Verify `CIBW_BUILD` setting in workflow includes their Python version
- Check workflow logs for build failures

### Wheels Contain Source Files

- Run `python scripts/verify_wheel.py dist/` to diagnose
- Check that `setup.py` custom build class is active
- Verify `pyproject.toml` has correct `exclude-package-data`

### Import Errors After Installation

- Ensure `__init__.py` files are present
- Check that binary extensions were built correctly
- Verify Python version compatibility

## References

- [cibuildwheel documentation](https://cibuildwheel.readthedocs.io/)
- [Cython documentation](https://cython.readthedocs.io/)
- [setuptools packaging guide](https://setuptools.pypa.io/en/latest/)

