## Security
- Before marking any task complete, run `./scripts/security-check.sh`
- Never hardcode API keys; all secrets must come from environment variables or .env
- Flag any new dependency additions for pip-audit review
- When modifying Dockerfile, run `trivy image` on the built image