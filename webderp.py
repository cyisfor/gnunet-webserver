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
oj = os.path.join

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
def processDirectory(info,path):
    doc = BeautifulSoup(directoryTemplate)
    presentInfo(doc,doc.find(id='info'),info)
    entries = doc.find(id='entries')
    def addEntry(chk,name,info):
        note.yellow('entry',name)
        entry = doc.new_tag('tr')
        td = doc.new_tag('td')
        td.append(chk[goofs+5:goofs+5+8])
        entry.append(td)
        td = doc.new_tag('td')
        a = doc.new_tag('a')
        a['href'] = name # relative links woo
        if info['mimetype'] == 'application/gnunet-directory':
            a['href'] += '/'
        a['id'] = chk # don't go to this, since we want to remember our parent directory
        a.append(name)
        td.append(a)
        entry.append(td)
        td = doc.new_tag('td')
        dl = doc.new_tag('dl')
        presentInfo(doc,dl,info)
        td.append(dl)
        entry.append(td)
        entries.append(entry)
    note.yellow('adding entries')
    yield gnunet.directory(path,addEntry)
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
        raise Return(self.write(blob))
    @tracecoroutine
    def sendfile(self,chk,name,info,temp,type,length):
        temp.seek(0,0)
        note.yellow('type',type,bold=True)
        if type is True or type == 'application/gnunet-directory':
            if self.filename:
                note.yellow('sub-entry here',self.filename,bold=True)
                # now find the chk/info of the filename in this directory
                gotit = False
                def oneResult(chk,name,info):
                    note.blue('name',name,chk,info,bold=True)
                    nonlocal gotit
                    if name == self.filename:
                        gotit = (chk,name,info)
                        return True
                yield gnunet.directory(temp.name,oneResult)
                if gotit:
                    chk,name,info = gotit
                    if info['mimetype'] == 'application/gnunet-directory':
                        if self.subsequent:
                            self.filename = self.subsequent.pop(0)
                        else:
                            self.filename = None
                    else:
                        assert not self.subsequent, "No subdirs below a normal file!"
                    # going down....
                    raise Return(self.startDownload(chk,name,info))
                else:
                    # a filename not in this directory.
                    self.write("Oh a wise guy, eh?")
                return
            # the directory itself, no sub-entry filename
            doc = yield processDirectory(info,temp.name)
            del temp
            raise Return(self.sendblob(str(doc).encode('utf-8'),'text/html'))
        elif type == 'text/html':
            doc = BeautifulSoup(temp)
            sanehtml.sanitize(doc)
            note.yellow('Sanitized')
            raise Return(self.sendblob(str(doc).encode('utf-8'),'text/html'))
        # XXX: this is wrong, and unsafe.
        elif type == 'text/css' or type == 'text/plain' and name.endswith('.css'):
            assert length < 0x10000
            contents = sanestyle.sanitize(temp.read(length).decode('utf-8'))
            raise Return(self.sendblob(contents.encode('utf-8'),'text/css'))
        elif type == 'application/x-shockwave-flash' and self.noflash:            
            raise Return(self.write("ha"))
        else:
            raise Return(super().sendfile(chk,name,info,temp,type,length))

Handler.default = os.environ['root']
if Handler.default.startswith('gnunet://fs'):
    Handler.default = Handler.default[len('gnunet://fs'):]

myserver.Server(Handler).listen(8444)
ioloop.IOLoop.instance().start()
