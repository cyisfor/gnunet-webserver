import baseserver
import gnunet

from bs4 import BeautifulSoup

directoryTemplate = '''<!DOCTYPE html><html>
<head>
</head>
<body>
<p>Listing for <span class="chk"/></p>
<ol id="entries"/>
</body>
</html>
'''

@tracecoroutine
def processDirectory(temp):
    entries = yield gnunet.directory(temp)
    doc = BeautifulSoup(directoryTemplate)


class Handler(baseserver.Handler):
    @tracecoroutine
    def sendfile(self,info,temp,type,length):
        if type == 'application/gnunet-directory':
            doc = processDirectory(temp)

Handler.default = os.environ['root']
if Handler.default.startswith('gnunet://fs'):
    Handler.default = Handler.default[len('gnunet://fs'):]

myserver.Server(Handler).listen(8444)
ioloop.IOLoop.instance().start()
