cat >files <<EOF
derpmagic.py
magic.py
myserver.py
note.py
EOF
rsync --files-from files -u -aPv ~/code/image/tagger/ ./
rsync --files-from files -u -aPv ./ ~/code/image/tagger/
