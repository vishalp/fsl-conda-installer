#!/usr/bin/env bash
pip install --upgrade pip setuptools wheel
pip install pytest coverage pytest-cov mock typing
pytest -v --cov=fslinstaller test
