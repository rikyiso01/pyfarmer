#!/bin/bash

set -e

cd "$(dirname "$0")"

rm -f destructivefarm/server/flags.sqlite

destructivefarm/server/start_server.sh