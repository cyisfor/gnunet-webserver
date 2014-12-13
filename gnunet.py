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

tmpdir = '/tmp/gnunet'
try: os.mkdir(tmpdir)
except OSError: pass

def tempo(ident,expires=None):
    return nanny.watch(lambda: ShenanigansTemporaryFile(ident,dir=tmpdir,expires=expires))

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

class DirectoryParser:
    getting = False
    chk = None
    name = None
    meta = None
    def __init__(self):
        self.results = []
    def take(self,line):
        if not self.getting:
            if dircontents.match(line):
                note.blue('yay self.getting',bold=True)
                self.getting = True
            continue
        if not self.chk:
            if line == '\n': break # eof here
            self.name,self.chk = line.rsplit(' (',1)
            self.chk = self.chk[:-3] # extra paren, colon, newline
            self.meta = {}
        else:
            line = line.strip()
            if line:
                if line[0] == '<':
                    match = embedded.match(line)
                    if match:
                        self.meta['size'] = match.group(1)
                else:
                    prop,value = line.split(': ',1)
                    self.meta[prop] = decode(prop,value)
            else:
                if examine:
                    finished = examine(self.chk,self.name,self.meta)
                    if finished:
                        diract.stdout.close()
                        break
                else:
                    self.results.append((self.chk,self.name,self.meta))
                self.chk = None
    def finish(self):
        assert self.chk is None, "Didn't finish parsing directory!"
        return self.results

@tracecoroutine
def directory(path,examine=None):
    if not examine:
        results = []
    diract,done = start('directory',path,stdout=STREAM)
    parser = DirectoryParser()
    while True:
        try: line = yield diract.stdout.read_until(b'\n')
        except StreamClosedError: break
        parser.take(line.decode('utf-8'))
    yield done
    if not examine:
        if not parser.results:
            note.yellow('warning, empty directory',path)
        raise Return(parser.finish())
    else:
        note('examining')

def cancellable(entries):
    class Cancellable(makeobj(entries)):
        action = None
        done = None
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
            self.done = done
            if self.cancelled:
                done.add_done_callback(self.nocancel)
                weakref.finalize(self,self.cancel)
                self.cancelled = False
            return done
    return Cancellable

class SearchProgress(cancellable({
    'amount': 0})):
    buffer = b''
    def __init__(self):
        self.parser = DirectoryParser()
        super().__init__()
    def watch(self,action,done):
        action.stdout.read_until_close(callback=self.dumpbuf,
                streaming_callback=partial(self.streaming,action))
        done.add_done_callback(self.dumpbuf)
        return super().watch(action,done)
    def dumpbuf(self):
        # final line might not be a newline (not really)
        self.parser.take(self.buffer.encode('utf-8'))
        self.parser.finish()
    def streaming(self,action,chunk):
        self.buffer += chunk
        note.magenta('search chunk',len(chunk))
        try: 
            sbuf = self.buffer.decode('utf-8')
            rawtail = None
        except UnicodeDecodeError as e: 
            sbuf = self.buffer[:e.start].decode('utf-8')
            rawtail = buffer[e.start:]
        lines = sbuf.split('\n')
        tail = lines[-1]
        lines = lines[:-1]
        # have to decode/re-encode to find where the newline is at the end.
        self.buffer = lines.encode('utf-8')
        if rawtail:
            self.buffer += rawtail
        for line in lines:
            self.parser.take(line)

class DownloadProgress(cancellable({
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

class Cache(pylru.lrucache):
    @tracecoroutine
    def proc(self,key,*a,**kw):
        try:
            watcher = self[key]
        except KeyError: 
            note.green('starting',self.start)
            watcher = yield self.start(key,*a,**kw)
            self[key] = watcher
            # or leave old watchers in cache? how to refresh then?
        # need to wait until either done, or a shorter timeout, then use the file if that second one
        # even if search is not done.
        # but try to return results sooner if we can.
        try: 
            code = yield gen.with_timeout(1000, watcher.done)
            note.magenta(type(self),'finished code',code)
        except gen.TimeoutError: pass
        raise Return(self.check(watcher,key,*a,**kw))

class Searches(Cache):
    @tracecoroutine
    def start(self, kw, limit=None,timeout=None):
        watcher = SearchProgress()
        if kw.startswith('gnunet://fs/sks/'):
            temp = tempo(kw[len('gnunet://fs/sks/'):].split('/')[0],expires=timeout/1000000)
        else:
            temp = tempo(kw.replace('%','%20').replace('/','%2f'),expires=timeout/1000000)
        watcher.isExpired = temp.isExpired
        if limit:
            limit = ('--results',str(limit))
        else:
            limit = ()
        if timeout is not None:
            expires = timeout
            timeout = ('--timeout',str(timeout))
        action,done = start(*("search","-V")+limit+timeout+(kw,),stdout=STREAM)
        watcher.watch(action,done)
        # don't leave old searches around... they change
        watcher.done.add_done_callback(lambda done: operator.delitem(self,kw))
        raise Return(watcher)
    def check(self, watcher, kw, limit=None, timeout=None):
        # the watcher builds results streamily, 
        # so to save us from yield directory(...) every time here.
        return watcher.parser.results

searches = Searches(0x800)
search = searches.proc # __call__ is confusing/slow

class Downloads(Cache):
    def start(self, chk, type=None, modification=None):
        watcher = DownloadProgress()
        # can't use with statement, since might be downloading several times from many connections
        # just have to wait for the file to be reference dropped / garbage collected...
        temp = tempo(chk[len('gnunet://fs/chk/'):].split('/')[0])
        watcher.temp = temp
        if temp.new:
            action,exited = start("download","--verbose","--output",temp.name,chk,stdout=STREAM)
            watcher.watch(action,exited)
            note('downloadid')
            exited.add_done_callback(lambda *a: temp.commit())
            exited.add_done_callback(lambda exited: self.finish(modification))
        # DO leave old downloads around... makes things way easier
        return watcher
    @tracecoroutine
    def check(self, watcher, chk, type=None, modification=None):
# comment this out enables partials
# comment this in enables status update?
# better to see a partial file, or a "still downloadan"?
#        if watcher.done.running():
#            return False
        note('got it?',watcher.done.running() is False)
        if not type:
            # XXX: what about partial files?
            type = derpmagic.guess_type(watcher.temp.fileno())[0]
            note.yellow('type guessed',type)
        length = 0
        # wait until we get at least SOME length.
        while True:
            watcher.temp.seek(0,2) # is this faster than fstat?
            length = watcher.temp.tell()
            if not watcher.done.running() or length > 0:
                break
            yield gen.with_timeout(1000,watcher.done)
        note('lengthb',length)
        watcher.temp.seek(0,0)
        # X-SendFile this baby
        # watcher.temp won't delete upon returning this, since not at 0 references
        # even though watcher is collected if watcher.done
        raise Return((watcher.temp,type,length))
    def finish(self,modification):
        if modification:
            note.yellow('mod',modification)
            os.utime(watcher.temp.name,(modification,modification))

# does not necessarily keep open files, but may accumulate lots of temp files on disk
# ( all should be deleted on program close )
# ( see nanny / mytemp for details )
downloads = Downloads(0x200)
download = downloads.proc

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
