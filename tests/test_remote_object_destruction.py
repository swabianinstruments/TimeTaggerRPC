import time

from TimeTaggerRPC.client import createProxy

TT = createProxy()

print('TT', TT._pyroUri)

# Find Time Taggers available at the remote system
print('Available Time Taggers',  TT.scanTimeTagger())

# Create Time Tagger
tagger = TT.createTimeTagger()
tagger.setTestSignal(1, True)
tagger.setTestSignal(2, True)

print('tagger', tagger._pyroUri, tagger.getSerial())

delayed_vch = TT.DelayedChannel(tagger, 2, 1000)
DELAYED_CH = delayed_vch.getChannel()

sm = TT.SynchronizedMeasurements(tagger)

hist_list = list()
for i in range(5):
    h = TT.Correlation(tagger, 1, DELAYED_CH, binwidth=10, n_bins=2000)
    print(f'hist_{i}', h._pyroUri)
    hist_list.append(h)
    sm.registerMeasurement(h)


crate = TT.Countrate(tagger, [1, 2])
print('crate', crate._pyroUri)
crate.clear()

sm.startFor(int(2e12), clear=True)

while sm.isRunning():
    time.sleep(0.05)

print('Countrates', crate.getData())

# del hist
crate._pyroRelease()
del crate

# TT.freeTimeTagger(tagger)
# del tagger

print('Sleeping ...')
time.sleep(5)
