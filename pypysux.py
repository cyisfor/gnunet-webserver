import weakref
if hasattr(weakref,'finalize'):
    finalize = weakref.finalize
else:
    # ugh... pypy...
    import atexit
    def finalize(what,op,*a,**kw):
        done = False
        def doop():
            nonlocal done
            if done: return
            done = True
            op(*a,**kw)
        weakref.ref(what,doop)
        atexit.register(doop)
        return doop
    weakref.finalize = finalize


