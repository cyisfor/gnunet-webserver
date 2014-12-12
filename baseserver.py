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

class Handler(myserver.ResponseHandler):
    code = 200
    message = "Otay"
    subsequent = None
    filename = None
    keyword = None
    ident = None
    def get(self):
        if self.path == '/':
            return self.redirect(self.default)
        else:
            self.breakdown()
            return getattr(self,'handle'+self.kind.upper())()
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
        
        # for sks, keyword must be parsed out, but filepath = keyword/filepathtail (or just keyword)
        # sks search = /sks/ident/keyword, sks filepath = keyword/filepathtail sigh

        # '/' in filepath implies directory
        # mimetype=application/gnunet-directory redirects to add '/' if not already isDir
        # ...because relative links screwed up if not end in '/'

        self.kind,rest = self.path[1:].split('/',1)
        self.ident,tail = rest.split('/',1)
        self.filepath,self.meta = self.parseMeta(tail)
        if '/' in self.filepath:
            self.isDir = True
        # check for mimetype directory later not now since SKS can add it
    oldCHK = None
    def handleSKS(self):
        # /sks/ident/keyword/filepathtail
        # with just keyword, these could be files
        # the directory is the chk result NOT the search itself.
        # filepath = keyword/filepathtail so same rules as CHK
        self.keyword = self.filepath.split('/',1)[0]
        self.uri = 'gnunet://fs/sks/'+self.ident+'/'+self.keyword
        try: 
            chk, name, info, expires = sksCache[(self.ident,self.keyword)]
            if expires >= time.time():
                # XXX: is this the best way to do this?
                gnunet.searches.remove(self.uri)
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
        results = yield gnunet.search(self.uri)
        results.sort(key=lambda result: result[-1]['publication date'])
        self.cleanSKS(results[:-1])
        chk, name, info = results[-1]
        if self.oldCHK and self.oldCHK != chk:
            # did a previous search expire that we need to confirm changed?
            gnunet.downloads.remove(self.oldCHK)
            self.oldCHK = None
        expiry = info.get(expiryName)
        if expiry:
            try: expiry = float(expiry)
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
        try: path, query = self.rest.split('?',1)
        except ValueError:
            path = self.rest
            info = {}
        else:
            info = dict((n,gnunet.decode(n,v)) for n,v in ((unquote(n),unquote(v)) for n,v in (e.split('=',1) for e in query.split('&'))))
            for n,long in self.queryShortcuts:
                if n in info:
                    info[long] = info[n]
                    del info[n]
        try: 
            self.ident, name = path.split('/',1)
        except ValueError:
            name = None
        chk = 'gnunet://fs/chk/' + self.ident
        # should we check if self.oldCHK is here, and set it to None if it matches?
        # how to "expire" downloads requested by CHK? Just wait for the cache to overflow, eh.
        info.setdefault('publication date',time.gmtime())
        return self.startDownload(chk,name,info)
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
            raise Redirect(self.path+'/')

        result = yield self.sendfile(chk,name,info,temp,type,length)
        raise Return(result)
    @tracecoroutine
    def sendfile(self,chk,name,info,temp,type,length):
        "override this to do things with the contents of the file, transform HTML, check for spam, list directories, etc"
        # note: the type argument is more reliable than info['mimetype'] 
        # as it's guessed from the file contents even if info has no mimetype record
        note('sending')
        temp.seek(0,0)
        yield self.send_header('Content-Type',type)
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
