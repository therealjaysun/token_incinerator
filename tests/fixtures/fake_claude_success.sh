#!/bin/bash
# Fake claude CLI that returns a successful JSON result
cat <<'EOF'
{"type":"result","is_error":false,"total_cost_usd":0.0234,"usage":{"input_tokens":2000,"output_tokens":800,"cache_read_input_tokens":100},"duration_ms":5100,"result":"Here is a comprehensive analysis of your codebase..."}
EOF
