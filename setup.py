from setuptools import Extension, setup
from setuptools.command.build_py import build_py
from Cython.Build import cythonize
import os

# Recursively find all .py files in the 'src' directory, excluding __init__.py
def find_py_files(directory):
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith(".py") and file != "__init__.py":
                yield os.path.join(root, file)

# Create a list of Extension modules for Cython
source_files = list(find_py_files("src"))
extensions = [
    Extension(
        name=os.path.splitext(os.path.relpath(path, "src"))[0].replace(os.path.sep, "."),
        sources=[path],
    )
    for path in source_files
]

class BuildPyExcludeCythonized(build_py):
    """
    Custom build_py that excludes .py files that have been cythonized.
    Only __init__.py files are kept as .py in the final wheel.
    """
    def find_package_modules(self, package, package_dir):
        modules = super().find_package_modules(package, package_dir)
        # Get list of modules that will be cythonized
        cythonized_modules = {
            ext.name for ext in extensions
        }
        # Filter out modules that are being cythonized
        filtered_modules = [
            (pkg, mod, file) for (pkg, mod, file) in modules
            if f"{pkg}.{mod}" not in cythonized_modules and mod != "__init__"
        ]
        # Keep __init__.py files
        filtered_modules.extend(
            [(pkg, mod, file) for (pkg, mod, file) in modules if mod == "__init__"]
        )
        return filtered_modules

setup(
    ext_modules=cythonize(
        extensions,
        compiler_directives={
            "language_level": "3",
            "embedsignature": True,  # Embed function signatures for help()
        },
        exclude_failures=True,
        # Use build_dir to keep intermediate C files out of the source tree
        build_dir="build/cython_build" 
    ),
    cmdclass={
        'build_py': BuildPyExcludeCythonized,
    },
)
