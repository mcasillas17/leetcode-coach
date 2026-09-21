"""Launch the installed local MCP server from any working directory."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from leetcode_coach.mcp_server import main
except ModuleNotFoundError as exc:
    if exc.name == 'mcp':
        raise SystemExit('Install requirements-mcp.txt into .venv and launch with .venv/bin/python.') from None
    raise

if __name__ == '__main__':
    main()
