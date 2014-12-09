def makeobj(*slots):
    class Object:
        __slots__ = slots
        def __init__(self,*a):
            for i,v in enumerate(a):
                setattr(self,slots[i],v)
        def __setitem__(self,i,v):
            setattr(self,slots[i],v)
    return Object
