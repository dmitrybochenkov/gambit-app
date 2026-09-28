#!/usr/bin/env bash

set -Eeuo pipefail

exec ssh -t dimension-x \
    'export PATH="$HOME/.local/bin:$PATH"; cd /opt/apps/gambit && scripts/deploy-production.sh'
