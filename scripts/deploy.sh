#!/usr/bin/env bash

set -Eeuo pipefail

exec ssh -t dimension-x 'cd /opt/apps/gambit && scripts/deploy-production.sh'
