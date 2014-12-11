def makeobj(entries):
    slots,defaults = zip(*entries.items())
    class Object:
        __slots__ = slots
        def __init__(self):
            for i,v in enumerate(defaults):
                setattr(self,slots[i],v)
        def __setitem__(self,i,v):
            setattr(self,slots[i],v)
    return Object
