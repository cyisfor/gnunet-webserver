import gnunet
import myserver

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

# new strategy, just be a downloader, progress monitor, and redirector
# i.e. start the download and print a page of progress, do recursive if directory
# then once it's done redirect to the file:// URL for that directory and/or file.
# maybe a tree of directories indexed by SKS/CHK?

# any who want to make cross-directory links can either do a CHK or an SKS like
# <a href="gnunet://fs/sks/...">...</a>
# and this server filters html/xhtml/markup/(css?) after saving, to make it 
# href="http://127.0.0.1:1235" instead.
# they can also do <a href="gnunet://fs/chk/...?metadata"> or <a mimetype=""... href="gnunet://fs/chk/..."> or the like

# make sure to change the directory name passed to .gnd (but link to /)

# http://host:port/kind/ident/trailer?chkmetadata
# -> progress on download and/or file://top/kind/ident/trailer.smartextension
# should also set user.mime_type attr if extended attrs possible in filesystem
# http://www.freedesktop.org/wiki/CommonExtendedAttributes/
# Content-Type http://redmine.lighttpd.net/projects/1/wiki/Mimetype_use-xattrDetails

# if kind is 'dir' metadata assumed to be mimetype=application/gnunet-directory

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
            self.kind,rest = self.path[1:].split('/',1)
            return getattr(self,'handle'+self.kind.upper())(rest)
    queryShortcuts = (
            ('p', 'publication date'),
            ('m', 'mimetype')
            )
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
    def breakdown(self,rest,):
        "Extract meaningful info we need from the URL"
        # /sks/ident/keyword/filepath?metadata
        # /dir/ident/keyword/filepath?metadata
        # /chk/ident/filepath?metadata
        # /dir/... implies directory
        # '/' in filepath implies directory
        # mimetype=application/gnunet-directory implies directory
        # mimetype in metadata otherwise ignored 
        # ...since file:// don't support it (maybe pass to a cheap web server?)
        self.ident,tail = rest.split('/',1)
        if not '/' in tail:
            # with just keyword, these are always directories
            # URLs for directories must end in / on the CLIENT side
            # ...for relative links to work right.
            return self.redirect(self.path+'/')
        self.keyword,tail = tail.split('/',1)
        self.filepath,meta = self.parseMeta(tail)
        if not self.isDir:
            if '/' in self.filepath:
                self.isDir = True
            # check for mimetype directory later since SSK can add it
    @tracecoroutine
    def handleSKS(self):
        # get the CHK for this SKS (the most recent one ofc)
        # do NOT yield futures right away, if not finished we want just progress report!
        results = gnunet.search('gnunet://fs/sks/'+self.ident+'/'+self.keyword)
        if results.running():
            raise Return(self.sendSearchProgress())
        else:
            results = results.result()
        results.sort(key=lambda result: result[-1]['publication date'])
        yield self.cleanSKS(results[:-1])
        chk, name, info = results[-1]
        info.update(meta) # get any metadata specified in the URL
        # note chk is not the ident unless kind is chk
        raise Return(self.startDownload(chk,name,info))
    @tracecoroutine
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
    def handleCHK(self):
        try: 
            self.ident, name = path.split('/',1)
        except ValueError:
            name = None
        chk = 'gnunet://fs/chk/' + self.ident
        name,info = self.parseMeta(name)
        return self.startDownload(chk,name,info)
    progress = None
    def startDownload(self,chk,name,info):
        "override this to do stuff if you don't care what the file type or publication date is"
        type = info.get('mimetype')
        modification = info.get('publication date')
        if not modification:
            modification = time.gmtime()
        modification = calendar.timegm(modification)
        return self.download(chk,name,info,type,modification)
    @tracecoroutine
    def download(self,chk,name,info,type,modification):
        "augment this to setup stuff according to the file type, HTML filters etc"
        # and by augment I mean override it, then call it w/ progress.

        # trouble... need to end in .partial.gnd if directory, but .partial if file.
        dest = buildPath(root,self.kind,self.ident,self.keyword,self.filepath+extension)
        partial = dest+'.partial'
        #hmm...
        self.isDir = self.subsequent or type == 'application/gnunet-directory'
        if self.subsequent
        future = gnunet.download(dest,chk,type,modification)
        if future.running():
            raise Return(self.sendDownloading(chk,name,info))
        else:
            temp,type,length = future.result()
            # tweak contents fix <a> to point to this server etc
            self.tweak(temp,type,length)
        if not temp.committed:
            temp.commit(dest)
            # filesystem attributes etc
            os.chmod(temp.fileno(),0o644)
            os.utime(temp.fileno(),(modification,modification))
            setxattr(temp,'Content-Type',type)
            setxattr(temp,'user.mime_type',type)
            setxattr(temp,'user.xdg.origin.url',chk)
        self.redirect('file://'+temp.name)
