import numpy as np
import matplotlib.pyplot as plt
from TimeTaggerRPC import client

TimeTagger = client.createProxy(host='localhost', port=23000)

print('Time Tagger software version (remote):', TimeTagger.getVersion())

# Create Time Tagger
tagger = TimeTagger.createTimeTagger()
tagger.setTestSignal(1, True)
tagger.setTestSignal(2, True)

print('Time Tagger serial:', tagger.getSerial())

hist = TimeTagger.Correlation(tagger, 1, 2, binwidth=5, n_bins=2000)
hist.startFor(int(10e12), clear=True)

fig, ax = plt.subplots()
h, = ax.plot([], [])
# the time vector is fixed. No need to read it on every iteration
x = hist.getIndex()
while hist.isRunning():
    plt.pause(0.1)
    y = hist.getData()
    h.set_data(x, y)
    ax.set_xlim(np.min(x), np.max(x))
    ax.set_ylim(np.min(y), np.max(y))

# Cleanup
TimeTagger.freeTimeTagger(tagger)
del hist
del tagger
del TimeTagger