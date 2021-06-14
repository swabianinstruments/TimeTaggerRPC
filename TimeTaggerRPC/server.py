import inspect
import logging
import enum

import Pyro5.api
import TimeTagger as TT

from . import helper


EXCLUDED_LIBRARY_MEMBERS = [
    'TimeTaggerBase', 'IteratorBase', 'Iterator', 'FlimAbstract',
    'TimeTaggerVirtual', 'createTimeTaggerVirtual',
    'CustomMeasurement', 'CustomMeasurementBase',
    'TimeTagStream', 'FileReader', 'TimeTagStreamBuffer',
    'setLogger', 'setCustomBitFileName', 'hasTimeTaggerVirtualLicense',
    'setFrontend', 'setLanguageInfo', 'flashLicense',
]

EXCLUDED_ITERATOR_ATTRIBUTES = [
    'waitUntilFinished',
]

EXCLUDED_TAGGER_ATTRIBUTES = [
    'factoryAccess'
]


def pyro_track_resource(resource):
    Pyro5.api.current_context.track_resource(resource)
    logging.debug('Tracking resource: %s', type(resource).__name__)


class TrackedResource:
    """Implements 'close' method that clears the underlying object.
        This class is not exposed by the Pyro and therefore its methods do
        not appear on the client proxy.
    """
    _obj: None

    def close(self):

        logging.debug('Close: %s', type(self).__name__)
        try:
            if issubclass(self._obj, TT.TimeTaggerBase):
                TT.freeTimeTagger(self._obj)
        except AttributeError:
            pass
        finally:
            self._obj = None


class Daemon(Pyro5.api.Daemon):
    """Customized Pyro5 Daemon."""

    def proxy2object(self, pyro_proxy):
        """Returns the Pyro object for a given proxy."""
        objectId = pyro_proxy._pyroUri.object
        return self.objectsById.get(objectId)


def make_module_function_proxy(func_name: str):
    """Generates a proxy method for the TimeTagger module level functions."""

    func = getattr(TT, func_name)
    assert inspect.isfunction(func)

    def func_proxy(self, *args, **kwargs):
        return func(*args, **kwargs)

    func_proxy.__name__ = func.__name__
    func_proxy.__doc__ = inspect.getdoc(func)
    func_proxy.__signature__ = inspect.signature(func)
    return func_proxy


def make_class_method_proxy(attrib: inspect.Attribute):
    """Generates a proxy method for the wrapped method
         Copies name, signature and doc-string.
    """
    assert attrib.kind == 'method', 'Must be a class method'

    def method_proxy(self, *args, **kwargs):
        method_handle = getattr(self._obj, attrib.name)
        return method_handle(*args, **kwargs)

    method_proxy.__doc__ = inspect.getdoc(attrib.object)
    method_proxy.__signature__ = inspect.signature(attrib.object)
    method_proxy.__name__ = attrib.name
    return method_proxy


def make_iterator_adapter_class(class_name: str):
    """Generates adapter class for the given Time Tagger iterator class
        and exposes them with Pyro.
    """
    iterator_class = getattr(TT, class_name)
    assert issubclass(iterator_class, TT.IteratorBase), 'Must be a TT.Iterator object.'

    # Custom init method
    def __init__(self, tagger_adapter, *args, **kwargs):
        TTClass = getattr(TT, type(self).__name__)
        self._obj = TTClass(tagger_adapter._obj, *args, **kwargs)
        pyro_track_resource(self)

    # Copy docstring and signature
    __init__.__doc__ = inspect.getdoc(iterator_class.__init__)
    __init__.__signature__ = inspect.signature(iterator_class.__init__)

    methods = {'__init__': __init__}

    # Iterate over all methods of the measurement and create proxy methods
    # print('iterator', class_name)
    for attrib in inspect.classify_class_attrs(iterator_class):
        if attrib.name in EXCLUDED_ITERATOR_ATTRIBUTES:
            continue
        if attrib.name.startswith('_'):
            continue
        if attrib.kind == 'method':
            # print('| --> ', attrib.name)
            methods[attrib.name] = make_class_method_proxy(attrib)

    # Expose class methods with Pyro
    IteratorAdapter = Pyro5.api.expose(type(class_name, (TrackedResource,), methods))
    return IteratorAdapter


def make_synchronized_measurements_adaptor_class():
    """Generates adapter class for the given Time Tagger iterator class
        and exposes them with Pyro.
    """
    Cls = TT.SynchronizedMeasurements
    class_name = Cls.__name__

    # Custom methods method
    def __init__(self, tagger_adaptor):
        self._obj = TT.SynchronizedMeasurements(tagger_adaptor._obj)
        pyro_track_resource(self)

    def registerMeasurement(self, measurement_proxy):
        iterator_adaptor = self._pyroDaemon.proxy2object(measurement_proxy)
        return self._obj.registerMeasurement(iterator_adaptor._obj)

    def unregisterMeasurement(self, measurement_proxy):
        iterator_adaptor = self._pyroDaemon.proxy2object(measurement_proxy)
        return self._obj.unregisterMeasurement(iterator_adaptor._obj)

    # Possible but does not work yet
    # def getTagger(self):
    #     tagger = self._obj.getTagger()
    #     # Requires separate adaptor generator
    #     # TimeTaggerAdaptor = make_timetagger_adapter_class(type(tagger).__name__)
    #     tagger_adaptor = TimeTaggerAdaptor(tagger)
    #     self._pyroDaemon.register(tagger_adaptor)
    #     return tagger_adaptor

    # Copy docstring and signature
    __init__.__doc__ = inspect.getdoc(Cls.__init__)
    __init__.__signature__ = inspect.signature(Cls.__init__)

    methods = {
        '__init__': __init__,
        'registerMeasurement': registerMeasurement,
        'unregisterMeasurement': unregisterMeasurement,
        # 'getTagger': getTagger,
        }

    # Iterate over all methods of the measurement and create proxy methods
    # print('object', class_name)
    for attrib in inspect.classify_class_attrs(Cls):
        if attrib.name in methods:
            continue
        if attrib.name in EXCLUDED_ITERATOR_ATTRIBUTES + ['getTagger']:
            continue
        if attrib.name.startswith('_'):
            continue
        if attrib.kind == 'method':
            # print(' --> ', attrib.name)
            methods[attrib.name] = make_class_method_proxy(attrib)

    # Expose class methods with Pyro
    IteratorAdapter = Pyro5.api.expose(type(class_name, (TrackedResource,), methods))
    return IteratorAdapter


def make_timetagger_adapter_class(class_name: str):
    """Generates adapter class for the TimeTagger object.
        The Adapter exposes all public methods except those from exclusion list.
    """

    tagger_class = getattr(TT, class_name)
    assert issubclass(tagger_class, TT.TimeTaggerBase), 'Must be a TT.TimeTaggerBase object.'

    # Custom init method
    def __init__(self, *args, **kwargs):
        TimeTaggerCreator = getattr(TT, 'create'+class_name)
        self._obj = TimeTaggerCreator(*args, **kwargs)
        pyro_track_resource(self)

    # Copy docstring adn signature
    __init__.__doc__ = inspect.getdoc(tagger_class.__init__)
    __init__.__signature__ = inspect.signature(tagger_class.__init__)

    methods = {'__init__': __init__}

    # Iterate over all methods of the measurement and create proxy methods
    # print('tagger', class_name)
    for attrib in inspect.classify_class_attrs(tagger_class):
        if attrib.name in EXCLUDED_TAGGER_ATTRIBUTES:
            continue
        if attrib.name.startswith('_'):
            continue
        if attrib.kind == 'method':
            # print(' --> ', attrib.name)
            methods[attrib.name] = make_class_method_proxy(attrib)

    # Expose class methods with Pyro
    TaggerAdapterClass = Pyro5.api.expose(type(class_name, (TrackedResource,), methods))
    return TaggerAdapterClass


def make_iterator_constructor(iterator_name: str):
    """Generates a method that constructs the Time Tagger Iterator object and its adaptor.
        The constructor method will be exposed via Pyro and allows creation of the measurements
        and virtual channels via the TimeTaggerRPC interface.
    """

    AdapterClass = make_iterator_adapter_class(iterator_name)

    def constructor(self, tagger_proxy, *args, **kwargs):
        tagger_adapter = self._pyroDaemon.proxy2object(tagger_proxy)
        pyro_obj = AdapterClass(tagger_adapter, *args, **kwargs)
        self._pyroDaemon.register(pyro_obj)
        return pyro_obj
    constructor.__name__ = AdapterClass.__name__
    constructor.__doc__ = inspect.getdoc(AdapterClass)
    constructor.__signature__ = inspect.signature(AdapterClass.__init__)
    return constructor


def make_synchronized_measurement_constructor():
    """Generates a method that constructs the SynchronizedMeasurements object and its adaptor.
        The constructor method will be exposed via Pyro and allows creation of the measurements
        and virtual channels via the TimeTaggerRPC interface.
    """

    AdapterClass = make_synchronized_measurements_adaptor_class()

    def constructor(self, tagger_proxy):
        tagger_adapter = self._pyroDaemon.proxy2object(tagger_proxy)
        pyro_obj = AdapterClass(tagger_adapter)
        self._pyroDaemon.register(pyro_obj)
        return pyro_obj
    constructor.__name__ = AdapterClass.__name__
    constructor.__doc__ = inspect.getdoc(AdapterClass)
    constructor.__signature__ = inspect.signature(AdapterClass.__init__)
    return constructor


def make_tagger_constructor(class_name: str):
    """Generates a method that constructs the Time Tagger object and its adaptor.
        The constructor method will be exposed via Pyro and allows creation
        of time taggers via the TimeTaggerRPC interface.
    """
    TimeTaggerAdaptor = make_timetagger_adapter_class(class_name)

    def constructor(self, *args, **kwargs):
        pyro_obj = TimeTaggerAdaptor(*args, **kwargs)
        self._pyroDaemon.register(pyro_obj)
        return pyro_obj
    constructor.__name__ = 'create'+TimeTaggerAdaptor.__name__
    constructor.__doc__ = inspect.getdoc(TimeTaggerAdaptor.__init__)
    constructor.__signature__ = inspect.signature(TimeTaggerAdaptor.__init__)
    return constructor


def make_timetagger_library_adapter():
    """Generates an adapter class for the Time Tagger library and exposes it with Pyro.
        This class is an entry point for remote connections.
    """

    # Manually defined functions and helpers
    def freeTimeTagger(self, tagger_proxy):
        tagger_adapter = self._pyroDaemon.proxy2object(tagger_proxy)
        return TT.freeTimeTagger(tagger_adapter._obj)

    TimeTaggerRPC_attributes = {
        "freeTimeTagger": freeTimeTagger,
    }

    TimeTagger_enums = dict()

    # Create classes
    for name, Cls in inspect.getmembers(TT, predicate=inspect.isclass):
        if name in EXCLUDED_LIBRARY_MEMBERS:
            continue
        if name.startswith('_'):
            continue
        if issubclass(Cls, TT.IteratorBase):
            TimeTaggerRPC_attributes[name] = make_iterator_constructor(name)
        elif issubclass(Cls, TT.TimeTaggerBase):
            TimeTaggerRPC_attributes['create'+name] = make_tagger_constructor(name)
        elif issubclass(Cls, TT.SynchronizedMeasurements):
            TimeTaggerRPC_attributes[name] = make_synchronized_measurement_constructor()
        elif issubclass(Cls, enum.Enum):
            enum_type = inspect.getmro(Cls)[1]
            enum_values = tuple((e.name, e.value) for e in Cls)
            if len(enum_values) > 0:
                TimeTagger_enums[name] = (enum_type.__name__, enum_values)
        elif name in ('Resolution', 'CoincidenceTimestamp', 'ChannelEdge'):
            # This case handles older TimeTagger versions that do not use "enum" package.
            if name in TimeTagger_enums:
                continue
            enum_type = 'IntEnum'  # Use IntEnum for all enums
            enum_values = list()
            for atr in inspect.classify_class_attrs(Cls):
                if not atr.name.startswith('_'):
                    enum_values.append((atr.name, atr.object))
            if len(enum_values) > 0:
                TimeTagger_enums[name] = (enum_type, tuple(enum_values))

    # Enum definitions getter
    TimeTaggerRPC_attributes['enum_definitions'] = lambda *args: TimeTagger_enums

    # Create module level functions
    for name, func in inspect.getmembers(TT, predicate=inspect.isfunction):
        if name in TimeTaggerRPC_attributes:
            continue
        if name in EXCLUDED_LIBRARY_MEMBERS:
            continue
        if name.startswith('_'):
            continue
        # print('function', name)
        TimeTaggerRPC_attributes[name] = make_module_function_proxy(name)

    # Construct and expose the final RPC adapter class
    TimeTaggerRPC = Pyro5.api.expose(type("TimeTaggerRPC", (), TimeTaggerRPC_attributes))
    return TimeTaggerRPC


def start_server(host='localhost', port=23000, use_ns=False, start_ns=False):
    """This method starts the Pyro server eventloop and processes client requests."""

    # Start Pyro nameserver in a subprocess
    if start_ns:
        import subprocess
        ns_proc = subprocess.Popen(
            ['python', '-m', 'Pyro5.nameserver', '-n', host])

    try:
        with Daemon(host=host, port=port) as daemon:
            # register native numpy arrays
            helper.register_numpy_handler()

            # Declare frontend
            if hasattr(TT, 'setFrontend') and hasattr(TT, 'FrontendType'):
                TT.setFrontend(TT.FrontendType.Pyro5RPC)

            # register the Pyro class
            TimeTaggerRPC = make_timetagger_library_adapter()
            rpc_obj = TimeTaggerRPC()
            uri = daemon.register(rpc_obj, 'TimeTagger')
            print('Server URI=', uri)
            if use_ns:
                ns = Pyro5.api.locate_ns()         # find the name server
                # register the object with a name in the name server
                ns.register("TimeTagger", uri)
            # start the event loop of the server to wait for calls
            daemon.requestLoop()
    except KeyboardInterrupt:
        pass
    finally:
        if start_ns:
            ns_proc.terminate()


def main():
    import argparse
    import textwrap

    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent(
            """\
            --------------------------------------------
            Swabian Instruments Time Tagger RPC Server.
            --------------------------------------------
            """
        )
    )
    parser.add_argument(
        '--host', type=str, dest='host', metavar='localhost', default='localhost',
        help='Hostname or IP on which the server will listen for connections.'
    )
    parser.add_argument(
        '--port', type=int, dest='port', default=23000, metavar='23000',
        help='Server port.'
    )
    parser.add_argument(
        '--use_ns', dest='use_ns', action='store_true',
        help='Use Pyro5 nameserver.'
    )
    parser.add_argument(
        '--start_ns', dest='start_ns', action='store_true',
        help='Start Pyro5 nameserver in a subprocess.'
    )

    args = parser.parse_args()

    start_server(**vars(args))


if __name__ == "__main__":
    main()
