import pypysux

import weakref
import tempfile
import os

class ShenanigansTemporaryFile:
    "A temporary file that can be opened and closed, but only deletes itself with no refs, or atexit"
    new = True
    def __init__(self,name=None,dir='/tmp',text=False,encoding=None, expires=None):
        if name is None:
            fd,path = tempfile.mkstemp(suffix='.tmp',dir=dir,text=False)
        else:
            path = os.path.join(dir,name)
            if os.path.exists(path) and ((expires is None) or (time.time() + expires > os.stat(path).st_mtime)):
                self.new = False
            else:
                path = path + '.tmp'
            encoding = encoding if encoding else 'utf-8' if text else None
        self.name = path
        if name is not None:
            mode = 'w+' if self.new else 'r+'
            mode += 't' if text else 'b'
            self.file = open(path, mode, encoding=encoding)
            if encoding or text:
                self.raw = self.file.raw
            else:
                self.raw = self.file
        else:
            self.raw = os.fdopen(fd,'w+b')
            if encoding:
                if encoding is True:
                    encoding = 'utf-8'
                self.file = io.TextIOWrapper(self.raw,encoding=encoding)
            else:
                self.file = self.raw
        weakref.finalize(self, self.ifnew, os.unlink, path)
    def isExpired(self,expires):
        return time.time() + expires < os.stat(fd=self.file.fileno()).st_mtime
    def ifnew(self,op,path):
        if self.new:
            op(path)
    def commit(self):
        # assumes not a tempfile...
        path = self.name[:-4]
        old = path+'.old'
        try: os.rename(path,old)
        except OSError: pass
        try:
            os.rename(self.name,path)
            self.name = path
        except:
            if os.path.exists(old):
                try: os.unlink(path)
                except OSError: pass
                os.rename(old,path)
        self.new = False
    def __getattr__(self,name):
        attr = getattr(self.file,name)
        setattr(self,name,attr)
        return attr
    def __repr__(self):
        return '<TemporaryFile '+self.name+'>'
    def __str__(self):
        return self.name
