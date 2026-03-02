#!/bin/sh
# docker-entrypoint.sh — seeds required Claude Code settings before starting Herald.
#
# The Herald container runs as root. Claude Code's CLI flag --dangerously-skip-permissions
# is blocked when running as root as a security measure. The settings.json key
# 'dangerouslySkipPermissions' also does not bypass tool permission checks — only the
# CLI flag does. Instead, we explicitly allow all tools via permissions.allow patterns,
# which works without restriction regardless of the running user.
#
# We always overwrite settings.json so that the correct permissions are applied even
# if an old file exists in the persistent herald_claude_memory volume.
mkdir -p /root/.claude
cat > /root/.claude/settings.json <<'EOF'
{
  "permissions": {
    "allow": [
      "Bash(*)",
      "Read(*)",
      "Write(*)",
      "Edit(*)",
      "Glob(*)",
      "Grep(*)",
      "Task(*)",
      "WebFetch(*)",
      "WebSearch(*)",
      "NotebookEdit(*)",
      "NotebookRead(*)"
    ]
  }
}
EOF

exec "$@"
