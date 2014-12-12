import derpmagic
import nanny
from mytemp import ShenanigansTemporaryFile
from coro import tracecoroutine

import pylru

import note
note.monitor(__name__)

from makeobj import makeobj

from tornado.process import Subprocess
from tornado import gen,ioloop
from tornado.iostream import StreamClosedError
from tornado.gen import Return

import subprocess as s

import weakref
from functools import partial,wraps
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

def cancellable(entries):
    class Cancellable(makeobj(entries)):
        action = None
        cancelled = True # starts out needing finalizing?
        def __init__(self):
            super().__init__()
        def cancel(self):
            if self.cancelled: return
            self.cancelled = True
            self.action.proc.terminate()
            self.action.stdout.close()
        def nocancel(self, future):
            self.cancelled = True
        def watch(self,action,done):
            self.action = action
            ioloop.IOLoop.instance().add_future(done,self.nocancel)
            if self.cancelled:
                weakref.finalize(self,self.cancel)
                self.cancelled = False
    return Cancellable

def finishable(entries):
    class Finishable(cancellable(entries)):
        finished = None
    return Finishable

class SearchProgress(finishable({
    'amount': 0})):
    def watch(self,action,done):
        super().watch(action,done)
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

    pattern = re.compile("^Downloading `.*?' at ([0-9]+)/([0-9]+) \\(([0-9]+) ms remaining, ([.0-9]+) (KiB|MiB|B)/s\\). Block took ([0-9]+) ms to download\n")
    @tracecoroutine
    def watch(self,action,done):
        super().watch(action,done)
        while True:
            try: line = yield action.stdout.read_until(b'\n')
            except StreamClosedError: break
            match = self.pattern.match(line.decode('utf-8'))
            if match:
                fields = ('current','total','remaining','rate','unit','lastblock') # SIGH
                for i,v in enumerate(match.groups()):
                    setattr(self,fields[i], v)
                if self.progress: 
                    self.progress()
    progress = None


searches = pylru.lrucache(0x800)

# does not necessarily keep open files, but may accumulate lots of temp files on disk
# ( all should be deleted on program close )
# ( see nanny / mytemp for details )
downloads = pylru.lrucache(0x200)

def cached(cache,Thingy,name):
    def decorator(f):
        @wraps(f)
        def wrapper(key,*a,**kw):
            try:
                result = cache[key]
                if result.finished.running():
                    note.green('already',name)
                else:
                    note.green('redoing',name,result.finished.result())
                return result.finished
            except KeyError: pass
            note.green('starting',name,bold=True)
            result = Thingy()
            cache[key] = result
            result.finished = f(result, key, *a, **kw)
            assert(result.finished)
            return result.finished
        return wrapper
    return decorator
    
@cached(searches,SearchProgress,'searching')
@tracecoroutine
def search(watcher, kw,limit=None):
    if limit:
        limit = ('--results',str(limit))
    else:
        limit = ()
    temp = tempo()

    action,done = start(*("search",)+limit+("--output",temp.name,"--timeout",str(timeout),kw),stdout=STREAM)
    watcher.watch(action,done)
    code = yield done
    note.magenta('code',code)
    results = yield directory(temp.name)
    assert results, kw
    del temp
    # temp file will be deleted now (for search results), since no more references
    # results.sort(key=lambda result: result[1]['publication date']) do this later
    raise Return(results)

@cached(downloads,DownloadProgress,'downloading')
@tracecoroutine
def download(watcher, chk, type=None, modification=None):
    # can't use with statement, since might be downloading several times from many connections
    # just have to wait for the file to be reference dropped / garbage collected...
    temp = tempo()
    action,exited = start("download","--verbose","--output",temp.name,chk,stdout=STREAM)
    watcher.watch(action,exited)
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
        note.yellow('mod',modification)
        os.utime(temp.name,(modification,modification))
    # X-SendFile this baby
    # temp won't delete upon returning this, since not at 0 references
    raise Return((temp,type,length))

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

def unindex(path):
    action,done = start("unindex",path)
    return done
