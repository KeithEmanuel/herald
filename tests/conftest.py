"""
conftest.py — pytest configuration for Herald tests.
"""
import sys
from pathlib import Path

# Add the project root to sys.path so tests can import Herald modules directly
sys.path.insert(0, str(Path(__file__).parent.parent))
