.PHONY: test check status report

test:
	python3 -W error::ResourceWarning -m unittest discover -s tests -v

check: test
	git diff --check

status:
	python3 -m leetcode_coach status

report:
	python3 -m leetcode_coach report
