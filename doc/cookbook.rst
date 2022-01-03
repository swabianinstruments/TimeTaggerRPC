##############
Cookbook
##############


Serving Time Tagger to multiple clients
==========================================


This section describes how to access the same Time Tagger object from multiple processes on one PC. 

In order to access the TimeTaggerRPC server from multiple PCs, you have to configure the server for providing access over the network.
This is done by starting the server with ``--host`` parameter and specifying explicit IP address ``<SERVER_IP>`` on which the server shall listen for connections.

.. code:: 

    TimeTaggerRPC-server --host <SERVER_IP>

On the client you can connect to the server as follows:

.. code:: python

    # Process 1
    from TimeTaggerRPC import client
    TT = client.createProxy(host='<SERVER_IP>')
    tagger_proxy = TT.createTimeTagger()
    tagger_proxy.getSerial()
    '1740000JG2'
    # Get the URI of the Time Tagger object.
    print(tagger_proxy._pyroUri)
    'PYRO:obj_b2d2c3cc61b8460d921dccededff8274@<SERVER_IP>:23000'

Now you can do on another process / PC the following

.. code:: python

    # Process 2
    from TimeTaggerRPC import client
    from Pyro5.api import Proxy

    # Access the Time Tagger library. 
    # It is always the same server object (singleton)
    TT = client.createProxy(host='<SERVER_IP>')  

    # Connect to the existing Time Tagger object by its URI
    uri = 'PYRO:obj_b2d2c3cc61b8460d921dccededff8274@<SERVER_IP>:23000'
    tagger_proxy = Proxy(uri)
    tagger_proxy.getSerial()
    '1740000JG2'
    # From now on you can create measurements as usual with your tagger_proxy
    cr = TT.Countrate(tagger_proxy, [1, 2])


This demonstrates how one can use multiple clients or processes to access the same Time Tagger.

.. warning:: 

    All clients connected to the same object have full control over it.
    For example, If any of the clients execute ``TT.freeTimeTagger(tagger_proxy)``,
    all clients using this object will be affected because the server received 
    a command to close the TimeTagger hardware connection.

Currently, there is no intention to implement access management code in the TimeTaggerRPC package. 
If you want to develop a common access infrastructure in your lab then you can follow one of the strategies

    1. Implement your own code based on the code from TimeTaggerRPC. 
    2. Implement your experiment code on the server and expose access to it using Pyro5 instead of only the Time Tagger alone.


Multithreading and proxy objects
=================================

The TimeTagger library is multithreaded and thread-safe, this means you can safely use Time Tagger objects from multiple threads.
However it is not the same when you use TimeTaggerRPC. The distinction is that 
the client code does not operate on the Time Tagger objects but on the Pyro5 proxy objects. 
The proxy objects maintain the network connection to the server and identify 
themselves with a single thread and disallow the use from multiple threads simultaneously.
However, it is possible to transfer the proxy object ownership to another thread.
This is done by calling special Pyro5 method ``Proxy._pyroClaimOwnership()`` present on each proxy object. 

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



Secure access using SSH port forwarding
=======================================

The Pyro5, and thus the TimeTaggerRPC, do not secure or encrypt their communication over the network. 
While it is usually fine to make server accessible in your local network, 
you are strongly discouraged to expose the server to a broad public. 

If you need to provide access to outside clients in a controlled way, you have a few options:

1. Setup :abbr:`SSH (Secure Shell)` port forwarding. [Easiest]
2. Setup access to the server over :abbr:`VPN (Virtual Private Network)`. [Moderate to complex]
3. Enable :abbr:`SSL (Secure Sockets Layer)` in Pyro5 and implement user authentication. [Complex]

This section describes how to provide secure access to the TimeTaggerRPC server using SSH port forwarding. 
It is the easiest, and in most situations sufficient, way of adding a layer of security and access control to your TimeTaggerRPC server.

You can learn more about SSH port forwarding
from `www.ssh.com <https://www.ssh.com/academy/ssh/tunneling/example>`_ 
and `this post <https://linuxize.com/post/how-to-setup-ssh-tunneling/>`_.

.. note::

    Before you set up any external access to your organization's network, 
    you are strongly advised to consult with your network administrator.

On the server computer
^^^^^^^^^^^^^^^^^^^^^^

1. Install, configure, and run the SSH server. Consult your operating system documentation on how to do this.

2. Run ``TimeTaggerRPC-server`` on a localhost only.

.. code::

    TimeTaggerRPC-server --host=localhost --port=23000


On the client computer
^^^^^^^^^^^^^^^^^^^^^^
1. Install SSH client. On many modern operating systems it is already available.

2. Setup SSH local port forwarding, so all communication to a local port will be forwarded to the remote port 23000.

.. code::

    # ssh -L LOCAL_PORT:DESTINATION_HOST:DESTINATION_PORT [USER@]SSH_SERVER
    # DESTINATION_HOST is specified as seen from the SSH_SERVER
    ssh -L 23001:localhost:23000 user@<SSH_SERVER>

3. Use the local port as if the TimeTaggerRPC server is listening on this port.

.. code:: python

    from TimeTaggerRPC import client
    TT = client.createProxy(host='localhost', port=23001)
    tagger_proxy = TT.createTimeTagger()
    print(tagger_proxy.getSerial())
    
    >> '1740000JG2'

