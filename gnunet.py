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
            if self.cancelled:
                done.add_done_callback(self.nocancel)
                weakref.finalize(self,self.cancel)
                self.cancelled = False
            return done
    return Cancellable

class SearchProgress(cancellable({
    'amount': 0})):
    def __init__(self):
        self.results = []
        super().__init__()
    def watch(self,action,done):
        action.stdout.read_until_close(callback=lambda *a: None,
                streaming_callback=partial(self.streaming,action))
        return super().watch(action,done)
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

class Cache(pylru.lrucache):
    @tracecoroutine
    def proc(self,*a,**kw):
        try:
            watcher = self[key]
        except KeyError: 
            note.green('starting',self.startup)
            watcher = yield self.startup(*a,**kw)
            self[key] = watcher
            # or leave old watchers in cache? how to refresh then?
        # need to wait until either done, or a shorter timeout, then use the file if that second one
        # even if search is not done.
        # but try to return results sooner if we can.
        try: 
            code = yield ioloop.with_timeout(1, watcher.done)
            note.magenta(type(self),'finished code',code)
        except ioloop.TimeoutError: pass
        raise Return(self.check(watcher,*a,**kw))

class Searches(Cache):
    @tracecoroutine
    def start(self, kw, limit=None,timeout=None):
        watcher = SearchProgress()
        if kw.startswith('gnunet://fs/sks/'):
            temp = tempo(kw[len('gnunet://fs/sks/'):].split('/')[0],expires=expires)
        else:
            temp = tempo(kw.replace('%','%20').replace('/','%2f'),expires=expires)
        watcher.isExpired = temp.isExpired
        if limit:
            limit = ('--results',str(limit))
        else:
            limit = ()
        if timeout is not None:
            expires = timeout
            timeout = ('--timeout',str(timeout))
        action,done = start(*("search","-V")+limit+timeout,stdout=STREAM)
        watcher.watch(action,done)
        # don't leave old searches around... they change
        watcher.done.add_done_callback(operator.delitem,self,key)
        return watcher
    def check(self, watcher, kw, limit=None, timeout=None):
        # the watcher builds results streamily, 
        # so to save us from yield directory(...) every time here.
        return watcher.results

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
            yield with_timeout(watcher.done,1)
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
