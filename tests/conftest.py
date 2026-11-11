"""Keep the skill directory clean: bytecode there makes validate_skill.py report stray files."""
import os
import sys

sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"  # inherited by subprocess-based tests
