import pypysux

import weakref
import tempfile
import os

class ShenanigansTemporaryFile:
    "A temporary file that can be opened and closed, but only deletes itself with no refs, or atexit"
    def __init__(self,dir='/tmp',text=False,encoding=None):
        fd,path = tempfile.mkstemp(dir=dir,text=False)
        self.name = path
        self.raw = os.fdopen(fd,'w+b')
        if encoding:
            if encoding is True:
                encoding = 'utf-8'
            self.file = io.TextIOWrapper(self.raw,encoding=encoding)
        else:
            self.file = self.raw
        weakref.finalize(self, os.unlink, path)
    def __getattr__(self,name):
        attr = getattr(self.file,name)
        setattr(self,name,attr)
        return attr
    def __repr__(self):
        return '<TemporaryFile '+self.name+'>'
    def __str__(self):
        return self.name
