from setuptools import Extension, setup
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

setup(
    ext_modules=cythonize(
        extensions,
        compiler_directives={"language_level": "3"},
        exclude_failures=True,
        # Use build_dir to keep intermediate C files out of the source tree
        build_dir="build/cython_build" 
    ),
)
