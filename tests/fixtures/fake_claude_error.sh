#!/bin/bash
# Fake claude CLI that simulates a non-zero exit (e.g. rate limit or auth error)
echo "Error: API request failed" >&2
exit 1
