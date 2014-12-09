import os,resource
import subprocess as s
import gc

def getmem():
    gc.collect()
    record = resource.getrusage(resource.RUSAGE_SELF)
    return record.ru_maxrss * resource.getpagesize()
initial = getmem()
s.call(['ps','v',str(os.getpid())])
bigbuf = bytearray(ord('Q') for i in range(1000000))
msize = getmem() - initial
print('size of a megabyte array: ',initial,msize)
current = getmem()
bufs = [bigbuf[1:] for i in range(100)]
hundredsize = getmem() - current
print('100 megabyte arrays: ',hundredsize,hundredsize/msize)
current = getmem()
buffs = [memoryview(bigbuf)[1:] for i in range(100)]
viewsize = getmem() - current
print('100 megabyte views: ',viewsize,hundredsize,viewsize/msize,hundredsize-viewsize,hundredsize/msize)

current = getmem()
derps = [bytes() for i in range(100)]
ehundsize = getmem() - current
print('100 megabyte arrays adj',ehundsize,hundredsize-ehundsize,(hundredsize-ehundsize)/msize)
