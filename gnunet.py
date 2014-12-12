import derpmagic
import nanny
from mytemp import ShenanigansTemporaryFile
from coro import tracecoroutine

import note
note.monitor(__name__)

from makeobj import makeobj

from tornado.process import Subprocess
from tornado import gen,ioloop
from tornado.iostream import StreamClosedError
from tornado.gen import Return

import subprocess as s

from functools import partial
import operator
import traceback
import time
import re
import os
import sys

STREAM = Subprocess.STREAM

timeout = 1000000 # 1 second

def tempo():
    return nanny.watch(ShenanigansTemporaryFile)

def decode(prop,value):
    if prop == 'publication date':
        return time.strptime(value,'%a %b %d %H:%M:%S %Y')
    elif prop.endswith('dimensions'):
        return tuple(int(i) for i in value.split('x'))
    return value

def encode(prop, value):    
    if hasattr(value,'tm_year'):
        return time.ctime(time.mktime(value))
    elif prop.endswith('dimensions'):
        return 'x'.join(map(str,value))
    else:
        return str(value)

anonymity = False

def start(op,*args,**kw):
    if anonymity:
        args = ('--anonymity',str(anonymity))+args
    done = gen.Future()
    note.cyan('gnunet-'+op+' '+' '.join(args))
    action = Subprocess(('gnunet-'+op,)+args,**kw)
    action.set_exit_callback(done.set_result)
    return action, done

embedded = re.compile('<original file embedded in ([0-9]+) bytes of meta data>')
dircontents = re.compile("Directory `.*?\' contents:\n")
@tracecoroutine
def directory(path,examine=None):
    if not examine:
        results = []
    diract,done = start('directory',path,stdout=STREAM)
    getting = False
    chk = None
    while True:
        try: line = yield diract.stdout.read_until(b'\n')
        except StreamClosedError: break
        line = line.decode('utf-8')
        if not getting:
            if dircontents.match(line):
                note.blue('yay getting',bold=True)
                getting = True
            continue
        if not chk:
            if line == '\n': break # eof here
            name,chk = line.rsplit(' (',1)
            chk = chk[:-3] # extra paren, colon, newline
            result = {}
        else:
            line = line.strip()
            if line:
                if line[0] == '<':
                    match = embedded.match(line)
                    if match:
                        result['size'] = match.group(1)
                else:
                    prop,value = line.split(': ',1)
                    result[prop] = decode(prop,value)
            else:
                if examine:
                    finished = examine(chk,name,result)
                    if finished:
                        diract.stdout.close()
                        break
                else:
                    results.append((chk,name,result))
                chk = None
    yield done
    if not examine:
        if not results:
            note.yellow('warning, empty directory',path)
        raise Return(results)
    else:
        note('examining')

class Cache(dict):
    maxCache = 0x200
    def __init__(self,maxCache=None):
        self.queue = []
        if maxCache:
            self.maxCache = maxCache
        super().__init__()
    def add(self,key,value):
        while len(self.queue) > self.maxCache:
            del self[self.queue.pop(0)]
        self[key] = value
        self.queue.append(key)
        return finished
    def remove(self,key):
        # assumes values have a cancel method
        try: self.queue.remove(key).cancel()
        except ValueError: return
        del self[key]

def cancellable(entries):
    entries['action'] = None
    entries['terminated'] = False
    class Cancellable(makeobj(entries)):
        __slots__ = super(Cancellable).__slots__
        def cancel(self):
            self.action.terminate()
            self.action.stdout.close()
        def watch(self,action):
            self.action = action
    return Cancellable

def finishable(entries):
    entries['finished'] = None
    class Finishable(cancellable(entries)):
        __slots__ = super(Finishable).__slots__
    return finishable

class SearchProgress(finishable({
    'amount': 0})):
    __slots__ = super(SearchProgress).__slots__
    def watch(self,action):
        super().watch(action)
        return action.stdout.read_until_close(callback=lambda *a: None,
                streaming_callback=partial(self.streaming,action))
    def streaming(self,action,chunk):
        note.magenta('search chunk',chunk)
        self.amount += len(chunk)

class DownloadProgress(finishable({
    'current': 0,
    'total': 1,
    'remaining': 0,
    'rate': 0,
    'unit': None,
    'lastblock': None})):
    __slots__ = super(DownloadProgress).__slots__
    @tracecoroutine
    def watch(self,action):
        super().watch(action)
        while True:
            try: line = yield action.stdout.read_until(b'\n')
            except StreamClosedError: break
            match = dw.match(line.decode('utf-8'))
            if match:
                for i,v in enumerate(match.groups()):
                    self[i+1] = v
                if self.progress: 
                    self.progress()
    progress = None

dw = re.compile("^Downloading `.*?' at ([0-9]+)/([0-9]+) \\(([0-9]+) ms remaining, ([.0-9]+) (KiB|MiB|B)/s\\). Block took ([0-9]+) ms to download\n")

searches = Cache(0x800)

# does not necessarily keep open files, but may accumulate lots of temp files on disk
# ( all should be deleted on program close )
# ( see nanny / mytemp for details )
downloads = Cache(0x200)

@tracecoroutine
def search2(watcher, kw,limit=None):
    if limit:
        limit = ('--results',str(limit))
    else:
        limit = ()
    temp = tempo()

    action,done = start(*("search",)+limit+("--output",temp.name,"--timeout",str(timeout),kw),stdout=STREAM)
    watcher.watch(action)
    code = yield done
    note.magenta('code',code)
    results = yield directory(temp.name)
    assert results, kw
    del temp
    # temp file will be deleted now (for search results), since no more references
    # results.sort(key=lambda result: result[1]['publication date']) do this later
    raise Return(results)

def addthingy(cache,key,Thingy,op,*a,**kw):
    thingy = Thingy()
    cache[kw] = thingy
    thingy.finished = op(thingy,*a,**kw)
    return thingy

def search(kw,limit=None):
    search = searches.get(kw)
    if search:
        note('already searcho',search.finished._result is not None)
        return search.finished
    return addthingy(searches,kw,SearchProgress,search2,kw,limit)

@tracecoroutine
def download2(watcher, chk, type, modification):
    # can't use with statement, since might be downloading several times from many connections
    # just have to wait for the file to be reference dropped / garbage collected...
    temp = tempo()
    action,exited = start("download","--verbose","--output",temp.name,chk,stdout=STREAM)
    watcher.watch(action)
    note('downloadid')
    yield exited
    note('got it')
    buf = bytearray(0x1000)
    if not type:
        type = derpmagic.guess_type(temp.fileno())[0]
        note.yellow('type guessed',type)
    temp.seek(0,2) # is this faster than fstat?
    length = temp.tell()
    note('lengthb',length)
    temp.seek(0,0)
    if modification:
        os.utime(temp.fileno(),(modification,modification))
    # X-SendFile this baby
    # temp won't delete upon returning this, since not at 0 references
    raise Return((temp,type,length))

def download(chk,progress=None, type=None, modification=None):
    download = downloads.get(chk)
    if download:
        note('already downloading',download.finished._result)
        return download.finished
    return addthingy(downloads,chk,DownloadProgress,download2,chk,type,modification)

@tracecoroutine
def indexed(take):
    action, done = start("fs","-i","-V",stdout=STREAM)
    while True:
        try: line = yield action.stdout.read_until(b'\n')
        except StreamClosedError: break
        if not line: break
        tinychk,name = line.split(b':')
        take(tinychk,name.strip())
    yield done

@tracecoroutine
def downloadSSK(ssk):
    results = yield search(ssk)
    results.sort(key=lambda result: result[-1]['publication date'])
    result = yield download(results[0][0])
    raise Return(result)

def unindex(path):
    action,done = start("unindex",path)
    return done
