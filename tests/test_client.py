import typing
import numpy as np
import matplotlib.pyplot as plt

from TimeTaggerRPC.client import createProxy


if typing.TYPE_CHECKING:
    import TimeTagger as TT
else:
    TT = createProxy()  #type: TT

# Find Time Taggers available at the remote system
print('Available Time Taggers',  TT.scanTimeTagger())

# Create Time Tagger
tagger = TT.createTimeTagger()  # type: TT.TimeTagger
tagger.setTestSignal(1, True)
tagger.setTestSignal(2, True)

print('tagger._pyroUri', tagger._pyroUri, tagger.getSerial())

delayed_vch = TT.DelayedChannel(tagger, 2, 1000)
DELAYED_CH = delayed_vch.getChannel()

hist = TT.Correlation(tagger, 1, 2, binwidth=10, n_bins=2000)
hist2 = TT.Correlation(tagger, 1, DELAYED_CH, binwidth=10, n_bins=2000)

print('hist ', hist._pyroUri)
print('hist2', hist2._pyroUri)

crate = TT.Countrate(tagger, [1,2])
crate.clear()

hist.startFor(int(10e12), clear=True)


fig, ax = plt.subplots()
h, = ax.plot([],[])
h2, = ax.plot([],[])
# the time vector is fixed. No need to read it on every iteration
x = hist.getIndex()
x2 = hist2.getIndex()
while hist.isRunning():
    plt.pause(0.1)
    y = hist.getData()
    y2 = hist2.getData()
    h.set_data(x, y)
    h2.set_data(x2, y2)
    ax.set_xlim(np.min(x), np.max(x))
    ax.set_ylim(np.min(y), np.max(y))

print('Countrates', crate.getData())

del hist
del crate

TT.freeTimeTagger(tagger)
del tagger
del TT
