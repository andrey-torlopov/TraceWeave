#!/bin/sh
set -eu
TW_SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec sh "$TW_SCRIPT_DIR/traceweave.sh" bootstrap "$@"
