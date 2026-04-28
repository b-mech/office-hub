#!/bin/bash
export PATH="/Users/nicholastenszen/.nvm/versions/node/v20.20.2/bin:$PATH"
set -a
source /Users/nicholastenszen/dev/office-hub/.env
set +a
cd /Users/nicholastenszen/dev/office-hub
overmind start
