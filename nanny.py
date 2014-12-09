from heapq import heappush,heappop,heapify

import pypysux
import weakref
import sys
if hasattr(sys,'getrefcount'):
    getrefcount = sys.getrefcount
else:
    # pypy...
    import gc
    def getrefcount(o):
        return len(gc.get_referrers(o))

resources = []
maxOpen = 0x100

'''The idea is:
you pass a routine that opens a file, get a file-like object back.
it adds to the total open files listed, and if too high starts closing files, BUT
if those files still have references, then any getattr or setattr to them will
reopen the file. It keeps the files to be closed in a heap, and removes the ones
with the lowest reference count.

THIS MAY CAUSE CHURN USE WITH CAUTION
'''
def adjust():
    heapify(resources)
    # we sadly can't track changes in reference counts and re-sort the heap each time.
    # that's O.K. though because these are scarce resources like files so heap size is small
    # hopefully if the count stays the same it's inexpensive to re-heapify a heapified list
    length = len(resources) + 1
    while length > maxOpen:
        heappop(resources).lose()
        length -= 1

class NannyProxy:
    'The proxy that loses or gains as its underlying resources is needed'
    rob = None
    closed = False
    def __init__(self,open):
        self.doopen = open
    def lose(self):
        self.closerob()
        del self.rob
    def gain(self):
        if not self.rob:
            self.rob = self.doopen()
            # this is so if the underlying file is closed, it auto-removes itself from this heap
            self.closerob = self.rob.close
            try: self.rob.close = self.clearlyLose
            except ValueError:
                print('WARNING: could not override close for',self.rob,file=sys.stderr)
            adjust()
            heappush(resources,self)
    def clearlyLose(self):
        try: resources.remove(self)
        except ValueError: pass
        self.close()
    def close(self):
        self.closed = True
        if self.rob:
            self.lose()
    def __lt__(self,other):
        if self.closed:
            return True
        if other.closed:
            return True
        return getrefcount(self) < getrefcount(other)

def watch(open):
    nanny = NannyProxy(open)
    weakref.finalize(nanny,nanny.close)
    class NannyMeth:
        def __getattr__(self,name):
            nanny.gain()
            return getattr(nanny.rob,name)
        def __setattr__(self,name,value):
            nanny.gain()
            setattr(nanny.rob,name,value)
        def __repr__(self):
            return repr(nanny.rob)
        def __str__(self):
            return str(nanny.rob)
    return NannyMeth()
