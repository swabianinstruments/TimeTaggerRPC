"""
This example demonstrates how to use Proxy objects in multiple Python threads.

Pyro5 does not allow access to Proxy objects from multiple threads.
However, one can transfer ownership of an existing Proxy object to another thread 
if required.

For more information see: 
    https://pyro5.readthedocs.io/en/latest/clientcode.html#proxy-sharing-between-threads

"""

import time
import threading
from TimeTaggerRPC import client


def thread_worker(crate, stop):
    # This thread claims ownership over Countrate proxy instance
    crate._pyroClaimOwnership()
    id = threading.get_ident()
    # Now we can use the proxy object in this thread
    while not stop.is_set():
        time.sleep(0.5)
        print('Thread', id, 'Countrate', crate.getData())


stop_evt = threading.Event()

TT = client.createProxy()  # Returns Pyro5 Proxy for the TimeTagger library

tagger = TT.createTimeTagger()  # Returns Pyro5 proxy for the TimeTagger object
tagger.setTestSignal(1, True)
tagger.setTestSignal(2, True)

# Create Countrate measurements and return their Pyro5 proxies
crate1 = TT.Counter(tagger, [1], binwidth=int(1e12), n_values=2) 
crate2 = TT.Counter(tagger, [2], binwidth=int(1e11), n_values=5)

# Create threads
t1 = threading.Thread(target=thread_worker, args=(crate1, stop_evt), daemon=True)
t2 = threading.Thread(target=thread_worker, args=(crate2, stop_evt), daemon=True)

try:
    t1.start()
    t2.start()
    while t1.is_alive() or t2.is_alive():
       time.sleep(0.1)

except KeyboardInterrupt:
    stop_evt.set()
    print('Exiting..')
finally:
    t1.join()
    t2.join()
    TT.freeTimeTagger(tagger)
