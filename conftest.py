"""Put the project root on sys.path so tests can import the flat modules."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
