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

from functools import partial
import operator
import traceback
import time
import re
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

anonymity = False

def start(op,*args,**kw):
    if anonymity:
        args = ('--anonymity',str(anonymity))+args
    done = gen.Future()
    action = Subprocess(('gnunet-'+op,)+args,**kw)
    action.set_exit_callback(done.set_result)
    return action, done

class Cache(dict):
    maxCache = 0x200
    def __init__(self,factory,maxCache=None):
        self.queue = []
        self.factory = factory
        if maxCache:
            self.maxCache = maxCache
    def add(self,key,finished,*a):
        value = self.factory(finished,*a)
        while len(self.queue) > self.maxCache:
            del self[self.queue.pop(0)]
        self[key] = value
        self.queue.append(key)
        return finished

SearchProgress = makeobj('finished','amount')
DownloadProgress = makeobj('finished','current','total','remaining','rate','unit','lastblock')

dw = re.compile("^Downloading `.*?' at ([0-9]+)/([0-9]+) \\(([0-9]+) ms remaining, ([.0-9]+) (KiB|MiB|B)/s\\). Block took ([0-9]+) ms to download\n")

searches = Cache(SearchProgress,0x800)

# does not necessarily keep open files, but may accumulate lots of temp files on disk
# ( all should be deleted on program close )
# ( see nanny / mytemp for details )
downloads = Cache(DownloadProgress,0x200) 

def watchSearch(kw,inp):
    def streaming(chunk):
        search = searches.get(kw)
        if not search: 
            inp.close()
            return
        search.amount += len(chunk)
    return inp.read_until_close(callback=lambda *a: None,streaming_callback=streaming)

@tracecoroutine
def search2(kw,limit=None):
    if limit:
        limit = ('--results',str(limit))
    else:
        limit = ()
    temp = tempo()

    action,done = start(*("search",)+limit+("--output",temp.name,"--timeout",str(timeout),kw),stdout=STREAM)
    watchSearch(kw,action.stdout)
    yield done
    results = []
    diract,done = start('directory',temp.name,stdout=STREAM)
    getting = False
    chk = None
    while True:
        try: line = yield diract.stdout.read_until(b'\n')
        except StreamClosedError: break
        line = line.decode('utf-8')
        if not getting:
            if line == 'Directory `(null)\' contents:\n': 
                getting = True
            continue
        if not chk:
            if line == '\n': break
            name,chk = line.rsplit(' (',1)
            chk = chk[:-3] # extra paren, colon, newline
            result = {}
        else:
            line = line.strip()
            if line:
                prop,value = line.split(': ',1)
                result[prop] = decode(prop,value)
            else:
                results.append((chk,name,result))
                chk = None
    del temp
    # temp file will be deleted now, since no more references
    # results.sort(key=lambda result: result[1]['publication date']) do this later
    yield done
    raise Return(results)

def search(kw,limit=None):
    search = searches.get(kw)
    if search:
        note('already searcho',search.finished._result is not None)
        return search.finished
    return searches.add(kw,search2(kw,limit),0)

@tracecoroutine
def watchDownload(chk,inp):
    while True:
        try: line = yield inp.read_until(b'\n')
        except StreamClosedError: break
        match = dw.match(line.decode('utf-8'))
        if match:
            download = downloads.get(chk)
            if not download:
                inp.close()
                return
            for i,v in enumerate(match.groups()):
                download[i+1] = v

@tracecoroutine
def download2(chk):
    # can't use with statement, since might be downloading several times from many connections
    # just have to wait for the file to be reference dropped / garbage collected...
    temp = tempo()
    action,exited = start("download","--verbose","--output",temp.name,chk,stdout=STREAM)
    watchDownload(action.stdout)
    yield exited
    buf = bytearray(0x1000)
    type = derpmagic.guess_type(temp.fileno())[0]
    temp.seek(0,2) # is this faster than fstat?
    length = temp.tell()
    note('lengthb',length)
    temp.seek(0,0)
    # X-SendFile this baby
    # temp won't delete upon returning this, since not at 0 references
    raise Return((temp,type,length))

def download(chk):
    download = downloads.get(chk)
    if download:
        note('already downloado',download.finished._result)
        return download.finished
    return downloads.add(chk,download2(chk),0,None)

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
