import numpy as np
import matplotlib.pyplot as plt
from TimeTaggerRPC import client

import TimeTagger as TT

TimeTagger: TT = client.createProxy(host='localhost', port=23000)

print('Time Tagger software version (remote):', TimeTagger.getVersion())

# Create Time Tagger
tagger = TimeTagger.createTimeTagger()
tagger.setTestSignal(1, True)
tagger.setTestSignal(2, True)
tagger.setTestSignal(3, True)

print('Time Tagger serial:', tagger.getSerial())

sm = TimeTagger.SynchronizedMeasurements(tagger)

try:
    sm.getTagger()
except AttributeError:
    raise NotImplementedError('SynchronizedMeasurements.getTagger() is not implemented on the server.')

hist1 = TimeTagger.Correlation(sm.getTagger(), 1, 2, binwidth=5, n_bins=2000)
hist2 = TimeTagger.Correlation(sm.getTagger(), 1, 3, binwidth=5, n_bins=2000)


sm.startFor(int(10e12), clear=True)

fig, ax = plt.subplots()
h1, = ax.plot([], [])
h2, = ax.plot([], [])
# the time vector is fixed. No need to read it on every iteration
x1 = hist1.getIndex()
x2 = hist2.getIndex()
while sm.isRunning():
    plt.pause(0.1)
    y1 = hist1.getData()
    y2 = hist2.getData()
    h1.set_data(x1, y1)
    h2.set_data(x2, y2)
    ax.set_xlim(np.min(x1), np.max(x1))
    ax.set_ylim(np.min(y1), np.max(y1))

# Cleanup
del hist1
del hist2
del sm

TimeTagger.freeTimeTagger(tagger)
del tagger
del TimeTagger