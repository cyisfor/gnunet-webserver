echo derpmagic.py magic.py myserver.py note.py > files
rsync --files-from files -u -aPv ~/code/image/tagger .
rsync --files-from files -u -aPv . ~/code/image/tagger
