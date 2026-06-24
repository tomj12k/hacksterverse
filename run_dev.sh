#!/usr/bin/env bash
set -euo pipefail

python -m hackster_studio.cli init-db
python -m hackster_studio.cli seed
python -m hackster_studio.cli run

