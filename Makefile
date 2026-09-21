.PHONY: test check check-mcp status report

test:
	python3 -W error::ResourceWarning -m unittest discover -s tests -v

check: test
	git diff --check

check-mcp:
	.venv/bin/python -W error::ResourceWarning -m unittest discover -s tests -v
	.venv/bin/python scripts/check_mcp.py
	git diff --check

status:
	python3 -m leetcode_coach status

report:
	python3 -m leetcode_coach report
