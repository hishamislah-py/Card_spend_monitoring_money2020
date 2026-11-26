#!/bin/sh
# server.py's main() binds 127.0.0.1; inside a container the edge needs 0.0.0.0, so start it via make_server().
set -e
cd /app
exec python -c "
import sys, ai, server
ai.load_env_file()
if not ai.api_key():
    print(ai.MISSING_KEY_MESSAGE, file=sys.stderr); sys.exit(1)
s = server.make_server(host='0.0.0.0', port=8000)
print('AG-101 Agent Spend Monitor on 0.0.0.0:8000, AI assist: Groq', s.app.ai.model)
s.serve_forever()
"
