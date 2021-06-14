
from TimeTaggerRPC.client import createProxy

with createProxy() as TT:
    print([v for v in dir(TT) if not v.startswith('_')])
    print(list(TT.ChannelEdge))
