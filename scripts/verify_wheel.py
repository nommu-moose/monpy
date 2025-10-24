#!/usr/bin/env python3
"""
Verify that wheels contain only binary files and __init__.py files.
No obfuscated .py source should be in the wheels (only in sdist).
"""
import sys
import zipfile
from pathlib import Path


def verify_wheel(wheel_path: Path) -> bool:
    """
    Check wheel contents and return True if valid (only binaries + __init__.py).
    """
    print(f"\n{'='*60}")
    print(f"Checking: {wheel_path.name}")
    print(f"{'='*60}")
    
    with zipfile.ZipFile(wheel_path, 'r') as zf:
        all_files = zf.namelist()
        
        # Find all .py files
        py_files = [f for f in all_files if f.endswith('.py')]
        init_files = [f for f in py_files if '__init__.py' in f]
        other_py_files = [f for f in py_files if '__init__.py' not in f]
        
        # Find all binary files
        binary_files = [f for f in all_files if f.endswith(('.pyd', '.so'))]
        
        print(f"\n📊 Summary:")
        print(f"  - Total files: {len(all_files)}")
        print(f"  - __init__.py files: {len(init_files)}")
        print(f"  - Other .py files: {len(other_py_files)}")
        print(f"  - Binary files (.pyd/.so): {len(binary_files)}")
        
        # Check for violations
        has_errors = False
        
        if other_py_files:
            print(f"\n❌ ERROR: Found {len(other_py_files)} non-__init__.py files:")
            for f in other_py_files[:10]:  # Show first 10
                print(f"     - {f}")
            if len(other_py_files) > 10:
                print(f"     ... and {len(other_py_files) - 10} more")
            has_errors = True
        else:
            print(f"\n✅ PASS: No source .py files (only __init__.py)")
        
        if not binary_files:
            print(f"\n⚠️  WARNING: No binary files found")
            has_errors = True
        else:
            print(f"\n✅ PASS: Found {len(binary_files)} binary files")
            
        # Show some binary files as examples
        if binary_files:
            print(f"\n📦 Sample binary files:")
            for f in binary_files[:5]:
                print(f"     - {f}")
            if len(binary_files) > 5:
                print(f"     ... and {len(binary_files) - 5} more")
        
        return not has_errors


def main():
    if len(sys.argv) < 2:
        print("Usage: python verify_wheel.py <wheel_file_or_directory>")
        sys.exit(1)
    
    path = Path(sys.argv[1])
    
    if path.is_file() and path.suffix == '.whl':
        wheels = [path]
    elif path.is_dir():
        wheels = list(path.glob('*.whl'))
    else:
        print(f"Error: {path} is not a wheel file or directory")
        sys.exit(1)
    
    if not wheels:
        print(f"No wheel files found in {path}")
        sys.exit(1)
    
    print(f"Found {len(wheels)} wheel(s) to verify")
    
    results = []
    for wheel in wheels:
        results.append(verify_wheel(wheel))
    
    print(f"\n{'='*60}")
    print(f"FINAL RESULTS")
    print(f"{'='*60}")
    passed = sum(results)
    failed = len(results) - passed
    print(f"✅ Passed: {passed}/{len(results)}")
    print(f"❌ Failed: {failed}/{len(results)}")
    
    if failed > 0:
        sys.exit(1)
    else:
        print("\n🎉 All wheels passed verification!")


if __name__ == "__main__":
    main()

