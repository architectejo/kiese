#!/bin/bash
cd /d/Projects/kiesse/backend
SP=$(cygpath -w "$1")
.venv/Scripts/python.exe manage.py shell -c "exec(open(r'$SP',encoding='utf-8').read())" 2>&1 | grep -v "objects imported"
