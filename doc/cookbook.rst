##############
Cookbook
##############


Serving Time Tagger to multiple clients
==========================================


This section describes how to access the same Time Tagger object from multiple processes on one PC. 
Access from multiple PCs is done the same way except you have to configure the server for providing access over the network.

.. code:: python

    # Process 1
    from TimeTaggerRPC import client
    TT = client.createProxy()
    tagger_proxy = TT.createTimeTagger()
    tagger_proxy.getSerial()
    '1740000JG2'
    # Get the URI of the Time Tagger object.
    print(tagger_proxy._pyroUri)
    'PYRO:obj_b2d2c3cc61b8460d921dccededff8274@localhost:23000'

Now you can do on another process / PC the following

.. code:: python

    # Process 2
    from TimeTaggerRPC import client
    from Pyro5.api import Proxy

    # Access the Time Tagger library. 
    # It is always the same server object (singleton)
    TT = client.createProxy()  

    # Connect to the existing Time Tagger object by its URI
    uri = 'PYRO:obj_b2d2c3cc61b8460d921dccededff8274@localhost:23000'
    tagger_proxy = Proxy(uri)
    tagger_proxy.getSerial()
    '1740000JG2'
    # From now on you can create measurements as usual with your tagger_proxy
    cr = TT.Countrate(tagger_proxy, [1, 2])


This demonstrates how one can use multiple clients or processes to access the same Time Tagger.
Warning, if one of the clients does something like 

.. code::

    TT.freeTimeTagger(tagger_proxy)

all of the clients using this object will be interrupted because the server received 
a command to close the TimeTagger hardware connection.

Currently, there is no intention to implement access management code in the TimeTaggerRPC package. 
If you want to develop a common access infrastructure in your lab then you can follow one of the strategies

    1. Implement your own code based on the code from TimeTaggerRPC. 
    2. Implement your experiment code on the server and expose access to it using Pyro5 instead of only the Time Tagger alone.


Multithreading and proxy objects
=================================

The TimeTagger library is multithreaded and thread-safe, this means you can safely use Time Tagger objects from multiple threads.
However it is not the same when you use TimeTaggerRPC. The distinction is that 
the client code does not operate on the Time Tagger objects but ont the the Pyro5 proxy objects. 
The proxy objects maintain the network connection to the server and identify 
themselves with a single thread and disallow the use from multiple threads simultaneously.
However, it is possible to transfer the proxy object ownership to another thread.
This is done by calling special Pyro5 method `Proxy._pyroClaimOwnership()` present on each proxy object. 

Take a look at the section 
`Proxy sharing between threads <https://pyro5.readthedocs.io/en/latest/clientcode.html#proxy-sharing-between-threads>`_
of Pyro5 documentation. There is also the related example in the Pyro5 repository
https://github.com/irmen/Pyro5/tree/master/examples/threadproxysharing.

The following example shows how this works.

.. code-block::

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

    TT = client.createProxy()  # Proxy for the TimeTagger library

    tagger = TT.createTimeTagger()  # Proxy for the TimeTagger object
    tagger.setTestSignal(1, True)
    tagger.setTestSignal(2, True)

    # Create Countrate measurements and return their Pyro5 proxies
    cr1 = TT.Counter(tagger, [1], binwidth=int(1e12), n_values=2) 
    cr2 = TT.Counter(tagger, [2], binwidth=int(1e11), n_values=5)

    # Create threads
    t1 = threading.Thread(target=thread_worker, args=(cr1, stop_evt))
    t2 = threading.Thread(target=thread_worker, args=(cr2, stop_evt))

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

