"""codegraph — language-agnostic code graph for analysis, PR review, and AI assistants."""
from importlib.metadata import PackageNotFoundError as _PackageNotFoundError
from importlib.metadata import version as _version

try:
    __version__ = _version("polycodegraph")
except _PackageNotFoundError:
    # Source checkout without install (rare — `pip install -e .` registers
    # the package and avoids this branch in normal dev setups).
    __version__ = "0.0.0+local"
