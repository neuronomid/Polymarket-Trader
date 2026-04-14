#!/bin/bash
cd "$(dirname "$0")"
PYTHONPATH=src .venv/bin/python3.13 src/__main__.py
