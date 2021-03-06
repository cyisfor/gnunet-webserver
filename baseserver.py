import gnunet
import myserver
from delaycache import DelayCache

import note
note.monitor(__name__)

from coro import tracecoroutine

from tornado import gen, ioloop, iostream
from tornado.gen import Return
iostream.bytes_type = object # duck typing, you morons!

from urllib.parse import unquote

from functools import partial
import calendar
import os
import operator
import time

def add_future(future,what):
    ioloop.IOLoop.instance().add_future(future,(lambda future: what(*future.result())))
    return future

sksCache = {}

expiryName = 'focal length 35mm' # libextractor sucks!

goofs = gnunet.goofs

class Handler(myserver.ResponseHandler):
    code = 200
    message = "Otay"
    subsequent = None
    filepath = None
    keyword = None
    ident = None
    def get(self):
        try: self.breakdown()
        except ValueError: pass
        print('kind',self.kind)
        return getattr(self,'handle'+self.kind.upper())()
    def internal(self):
        self.write('serve static stuff from where self.path is')
    def parseMeta(self, path):
        try: path, query = path.split('?',1)
        except ValueError:
            return path, {}
        info = dict((n,gnunet.decode(n,v)) for n,v in ((unquote(n),unquote(v)) for n,v in (e.split('=',1) for e in query.split('&'))))
        for n,long in self.queryShortcuts:
            if n in info:
                info[long] = info[n]
                del info[n]
        return path,info
    isDir = False
    def breakdown(self):
        "Extract meaningful info we need from the URL"
        # /sks/ident/keyword/filepathtail?metadata
        # /chk/ident/filepath?metadata
        # /status/
        # /status/ident/kind
        # /status/ident/kind/action
        
        # for sks, keyword must be parsed out, but filepath = keyword/filepathtail (or just keyword)
        # sks search = /sks/ident/keyword, sks filepath = keyword/filepathtail sigh

        # '/' in filepath implies directory
        # mimetype=application/gnunet-directory redirects to add '/' if not already isDir
        # ...because relative links screwed up if not end in '/'

        self.kind = self.path[1:]
        self.kind,self.rest = self.kind.split('/',1)
        try: 
            self.ident,tail = self.rest.split('/',1)
        except ValueError:
            self.ident,self.meta = self.parseMeta(self.rest)
            self.isDir = self.rest.endswith('/')
            return
        self.filepath,self.meta = self.parseMeta(tail)
        self.isDir = True
        # check for mimetype directory later not now since SKS can add it
    oldCHK = None
    def handleSKS(self):
        # /sks/ident/keyword/filepathtail
        # with just keyword, these could be files
        # the directory is the chk result NOT the search itself.
        # filepath = keyword/filepathtail so same rules as CHK
        try: self.keyword,self.filepath = self.filepath.split('/',1)
        except ValueError:
            self.keyword = self.filepath
            self.filepath = None
        self.uri = goofs+'/sks/'+self.ident+'/'+self.keyword
        try: 
            chk, name, info, expires = sksCache[(self.ident,self.keyword)]
            if expires >= time.time():
                # XXX: is this the best way to do this?
                try: del gnunet.searches[self.uri]
                except KeyError: pass
                # ......XXX: this is getting called many times
                return self.startDownload(chk,name,info)
            else:
                self.oldCHK = chk # don't remove this YET 
                # not until the search confirms it's gone
        except KeyError: pass
        return self.lookup()
    defaultExpiry = 600
    @tracecoroutine
    def lookup(self):
        # get the CHK for this SKS (the most recent one ofc)
        try: results = yield gnunet.search(self.uri,timeout=1000000*self.defaultExpiry)
        except ioloop.TimeoutError:
            try: searches[self.uri].pause()
            except KeyError: pass
            raise
        results = gnunet.searches[self.uri].parser.results
        if not results:
            self.write("No results yet bleh "+self.uri+'\n')
            return
        results.sort(key=lambda result: result[-1]['publication date'])
        self.cleanSKS(results[:-1])
        chk, name, info = results[-1]
        if self.oldCHK and self.oldCHK != chk:
            # did a previous search expire that we need to confirm changed?
            try: del gnunet.downloads[self.oldCHK]
            except KeyError: pass
            self.oldCHK = None
        expiry = info.get(expiryName)
        if expiry:
            try: 
                expiry = float(expiry)
                if gnunet.searches[self.uri].isExpired(expiry):
                    del gnunet.searches[self.uri]
                    raise Return(self.lookup())
            except ValueError:
                expiry = self.defaultExpiry
        else:
            expiry = self.defaultExpiry
        sksCache[(self.ident,self.keyword)] = (chk,name,info,time.time()+expiry)
        raise Return(self.startDownload(chk,name,info))
    def cleanSKS(self,oldinfos):
        indexfiles = {}
        yield gnunet.indexed(lambda tinychk,name: operator.setitem(indexfiles,tinychk.decode(),name))
        good = results[-1]
        results = results[:-1]
        note(indexfiles.keys())
        for chk,*rest in results:
            tinychk = chk[0x10:0x10+8].upper()
            name = indexfiles.get(tinychk)
            if name:
                note('unindex',name)
                yield gnunet.unindex(name)
    queryShortcuts = (
            ('p', 'publication date'),
            ('m', 'mimetype')
            )
    def handleCHK(self):
        chk = goofs + '/chk/' + self.ident
        # should we check if self.oldCHK is here, and set it to None if it matches?
        # how to "expire" downloads requested by CHK? Just wait for the cache to overflow, eh.
        self.meta.setdefault('publication date',time.gmtime())
        return self.startDownload(chk,self.filepath,self.meta)
    def startDownload(self,chk,name,info):
        "override this to do stuff if you don't care what the file type or publication date is"
        self.meta.update(info) # this seems a weird place to update this.
        type = self.meta.get('mimetype')
        modification = calendar.timegm(info['publication date'])
        return self.download(chk,name,self.meta,type,modification)
    @tracecoroutine
    def download(self,chk,name,info,type,modification):
        "augment this to setup stuff according to the file type, HTML filters etc"

        # in here you handle the type and modification 
        # instead of re-parsing them out of the info
        # is this too much granularity?

        temp,type,length = yield gnunet.download(chk,type,modification)
        # and now we have the best hope to know the type
        if not self.isDir and type == 'application/gnunet-directory':
            note.blue('making dirifydiret')
            self.redirect(self.path+'/')
        result = yield self.sendfile(chk,name,info,temp,type,length)
        raise Return(result)
    @tracecoroutine
    def sendfile(self,chk,name,info,temp,type,length):
        "override this to do things with the contents of the file, transform HTML, check for spam, list directories, etc"
        # note: the type argument is more reliable than info['mimetype'] 
        # as it's guessed from the file contents even if info has no mimetype record
        note('sending',type)
        temp.seek(0,0)
        assert type, 'bleh'
        yield self.send_header('Content-Type',type+'; charset=utf-8')
        modified = info.get('publication date')
        if modified:
            yield self.send_header('Last-Modified',self.date_time_string(modified))
        yield self.set_length(length)
        yield self.end_headers()
        buf = bytearray(0x1000)
        total = 0
        # Can't use X-SendFile because it offers no notification of when the file has
        # been started sending (and can be deleted) or has been sent.
        while True:
            amt = temp.readinto(buf)
            if amt <= 0: break
            total += amt
            yield self.write(memoryview(buf)[:amt])
        del temp
        # don't return temp, so that it can be garbage collected
        raise Return((info,type,length))
