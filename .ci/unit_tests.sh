#!/usr/bin/env bash


# The fsl package is a native namespace package, meaning that it
# does not have a __init__.py. Native namespace packages are not
# supported in Python < 3.3.
#
# https://packaging.python.org/guides/packaging-namespace-packages/
if python -c 'import sys; sys.exit(sys.version_info[:2] >= (3, 3))'; then
  touch fsl/__init__.py
fi


pip install --upgrade pip setuptools wheel
pip install pytest coverage pytest-cov mock typing

# some tests will fail if run as root
chmod a+rwx .
su -s /bin/bash nobody -c "pytest -m      noroottest  --cov-report= --cov-append"
pytest -m "not noroottest"
