import baseserver
import myserver
import gnunet

import sanehtml,sanestyle

import note

from coro import tracecoroutine

from tornado import ioloop
from tornado.gen import Return
from bs4 import BeautifulSoup

import calendar
from urllib.parse import quote

import os

directoryTemplate = '''<!DOCTYPE html><html>
<head>
</head>
<body>
<p>Listing for <span class="chk"/></p>
<dl id="info"/>
<table id="entries">
<th>CHK</th><th>Filename</th><th>Info</th>
</table>
</body>
</html>
'''

def presentInfo(doc,dl,info):
    for n,v in info.items():
        dt = doc.new_tag('dt')
        dt.append(n)
        dd = doc.new_tag('dd')
        dd.append(gnunet.encode(n,v))
        dl.append(dt)
        dl.append(dd)

goofs = len('gnunet://fs')

def buildLink(chk,name,info):
    href = chk
    if name:
        href += '/' + name
    if info:
        href += '?' + '&'.join(quote(n)+'='+quote(gnunet.encode(n,v)) for n,v in info.items())
    return href

@tracecoroutine
def processDirectory(parentchk,info,temp):
    doc = BeautifulSoup(directoryTemplate)
    presentInfo(doc,doc.find(id='info'),info)
    entries = doc.find(id='entries')
    def addEntry(chk,name,info):
        note.yellow('entry',name)
        entry = doc.new_tag('tr')
        td = doc.new_tag('td')
        a = doc.new_tag('a')
        a['href'] = buildLink('/dir'+parentchk[goofs+4:],name,info)
        a['title'] = chk # don't go to this, since we want to remember our parent directory
        a.append(chk[goofs+5:goofs+5+8].upper())
        td.append(a)
        entry.append(td)
        td = doc.new_tag('td')
        td.append(name)
        entry.append(td)
        td = doc.new_tag('td')
        dl = doc.new_tag('dl')
        presentInfo(doc,dl,info)
        td.append(dl)
        entry.append(td)
        entries.append(entry)
    note.yellow('adding entries')
    yield gnunet.directory(temp.name,addEntry)
    raise Return(doc)

class Handler(baseserver.Handler):
    def __init__(self,*a,**kw):
        note.magenta("Creating a Handler!",id(self))
        super().__init__(*a,**kw)
    @tracecoroutine
    def sendblob(self,blob,type):
        yield self.send_header('Content-Type',type)
        yield self.set_length(len(blob))
        yield self.end_headers()
        yield self.write(blob)
        note('wrote blob',type)
    isdir = False
    def handleDIR(self):
        self.isdir = True
        return self.handleCHK()
    def startDownload(self,chk,name,info):
        note.magenta('starting to download',chk[goofs:goofs+8],name)
        if self.isdir:
            type = True
            # don't need this to go to the next in the pipeline!
            del self.isdir 
        else:
            type = info.get('mimetype')
        modification = calendar.timegm(info['publication date'])
        return self.download(chk,name,info,type,modification)
    @tracecoroutine
    def sendfile(self,chk,sub,info,temp,type,length):
        temp.seek(0,0)
        note.yellow('type',type,bold=True)
        if type is True or type == 'application/gnunet-directory':
            # XXX: if the sub-entry, is a subdirectory, switch to that for a chk?
            if sub:
                note.yellow('sub-entry here',sub,bold=True)
                # getting a directory entry here...
                # note if this is a directory entry then info['mimetype'] is correct for it
                # but we still need the chk of it, so...
                gotit = False
                def oneResult(chk,name,info):
                    note.blue('name',name,chk,info,bold=True)
                    nonlocal gotit
                    if name == sub:
                        # sigh...
                        #self.send_status(302,'over here')
                        #self.send_header('Location',buildLink(chk[goofs:],name,info))
                        #self.end_headers()
                        gotit = (chk,name,info)
                        return True
                yield gnunet.directory(temp.name,oneResult)
                if gotit:
                    name,chk,info = gotit
                    if info['mimetype'] == 'application/gnunet-directory':
                        yield self.redirect('/dir'+chk[goofs+4:]+'/')
                    else:
                        # can't redirect to these since we need to allow relative links!
                        yield self.startDownload(name,chk,info)
                else:
                    self.write("Oh a wise guy, eh?")
                return
            doc = yield processDirectory(chk,info,temp)
            del temp
            yield self.sendblob(str(doc).encode('utf-8'),'text/html')
        elif type == 'text/html':
            doc = BeautifulSoup(temp)
            sanehtml.sanitize(doc)
            note.yellow('Sanitized')
            yield self.sendblob(str(doc).encode('utf-8'),'text/html')
        # XXX: this is wrong, and unsafe.
        elif type == 'text/css' or type == 'text/plain' and sub.endswith('.css'):
            assert length < 0x10000
            contents = sanestyle.sanitize(temp.read(length).decode('utf-8'))
            yield self.sendblob(contents.encode('utf-8'),'text/css')
        elif type == 'application/x-shockwave-flash' and self.noflash:
            yield self.set_length(0)
        else:
            yield super().sendfile(chk,sub,info,temp,type,length)

Handler.default = os.environ['root']
if Handler.default.startswith('gnunet://fs'):
    Handler.default = Handler.default[len('gnunet://fs'):]

myserver.Server(Handler).listen(8444)
ioloop.IOLoop.instance().start()
