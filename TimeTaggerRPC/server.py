import inspect
import logging
import enum

import Pyro5.api
import TimeTagger as TT

from . import helper


EXCLUDED_LIBRARY_MEMBERS = [
    'TimeTaggerBase', 'IteratorBase', 'Iterator', 'FlimAbstract',
    'TimeTaggerVirtual', 'createTimeTaggerVirtual',
    'CustomMeasurement', 'CustomMeasurementBase', 'CustomMeasurementBase_stop_all_custom_measurements',
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

class TrackedResource:
    """Implements 'close' method that clears the underlying object.
        This class is not exposed by the Pyro and therefore its methods do
        not appear on the client proxy.
    """
    _obj: object = None

    def __init__(self, obj):
        self._obj = obj
        Pyro5.api.current_context.track_resource(self)
        logging.debug('Tracking resource: %s', type(self).__name__)

    def close(self):
        logging.debug('Close: %s', type(self).__name__)
        try:
            if isinstance(self._obj, TT.TimeTaggerBase):
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


def make_class_attribute_proxy(attrib: inspect.Attribute):
    """Generates a proxy method for the wrapped method or property
         Copies name, signature and doc-string.
    """

    if attrib.kind == 'method':
        # Wrapper that forwards call to self._obj.<attrib.name>(*ars, **kwargs)
        def class_method(self, *args, **kwargs):
            method = getattr(self._obj, attrib.name)
            return method(*args, **kwargs)
        class_method.__doc__ = inspect.getdoc(attrib.object)
        class_method.__signature__ = inspect.signature(attrib.object)
        class_method.__name__ = attrib.name
        return class_method
    elif attrib.kind == 'property':
        # Wrapper that forwards the call to self._obj.<property>
        fget = lambda self: getattr(self._obj, attrib.name)
        fset = lambda self, value: setattr(self._obj, attrib.name, value)
        fdel = lambda self: delattr(self._obj, attrib.name)
        doc = inspect.getdoc(attrib.object)
        return property(fget, fset, fdel, doc)
    else:
        raise ValueError('Unknown attribute kind %s', attrib.kind)


def make_data_object_adaptor_class(class_name):
    """Generates adaptor class for DataObject returned by Iterator.getDataObject()."""

    assert class_name.endswith('Data'), 'Must be a DataObject object.'        
    TTClass = getattr(TT, class_name)

    attributes = {}

    # Iterate over all methods of the measurement and create proxy methods
    # print('DataObject', class_name)
    for attrib in inspect.classify_class_attrs(TTClass):
        if attrib.name.startswith('_'):
            continue
        if attrib.name.startswith('this'):
            continue
        # print('| --> ', attrib.kind, attrib.name)
        attributes[attrib.name] = make_class_attribute_proxy(attrib)

    # Expose class methods with Pyro
    DataObjectAdapter = type(class_name, (TrackedResource,), attributes)
    return Pyro5.api.expose(DataObjectAdapter)


def make_iterator_adapter_class(class_name: str):
    """Generates adapter class for the given Time Tagger iterator class
        and exposes them with Pyro.
    """
    iterator_class = getattr(TT, class_name)
    assert issubclass(iterator_class, TT.IteratorBase), 'Must be a TT.Iterator object.'

    attributes = {}

    if hasattr(iterator_class, 'getDataObject'):
        def getDataObject(self, *args, **kwargs):
            data_obj = self._obj.getDataObject(*args, **kwargs)
            pyro_obj = self._DataObjectAdapter(data_obj)
            self._pyroDaemon.register(pyro_obj)
            return pyro_obj
        getDataObject.__doc__ = inspect.getdoc(iterator_class.getDataObject)
        getDataObject.__signature__ = inspect.signature(iterator_class.getDataObject)
        attributes['_DataObjectAdapter'] = make_data_object_adaptor_class(class_name+'Data')
        attributes['getDataObject'] = getDataObject

    # Iterate over all methods of the measurement and create proxy methods
    # print('iterator', class_name)
    for attrib in inspect.classify_class_attrs(iterator_class):
        if attrib.name in attributes:
            continue
        if attrib.name in EXCLUDED_ITERATOR_ATTRIBUTES:
            continue
        if attrib.name.startswith('_'):
            continue
        if attrib.kind == 'method':
            # print('| --> ', attrib.name)
            attributes[attrib.name] = make_class_attribute_proxy(attrib)

    # Expose class methods with Pyro
    IteratorAdapter = type(class_name, (TrackedResource,), attributes)
    return Pyro5.api.expose(IteratorAdapter)


def make_synchronized_measurements_adaptor_class():
    """Generates adapter class for the given Time Tagger iterator class
        and exposes them with Pyro.
    """
    Cls = TT.SynchronizedMeasurements

    def registerMeasurement(self, measurement_proxy):
        iterator_adaptor = self._pyroDaemon.proxy2object(measurement_proxy)
        return self._obj.registerMeasurement(iterator_adaptor._obj)

    def unregisterMeasurement(self, measurement_proxy):
        iterator_adaptor = self._pyroDaemon.proxy2object(measurement_proxy)
        return self._obj.unregisterMeasurement(iterator_adaptor._obj)

    # Possible but does not work yet
    def getTagger(self):
        raise NotImplementedError('This method is not implemented.')
        # tagger = self._obj.getTagger()
        # # Requires separate adaptor generator
        # # TimeTaggerAdaptor = make_timetagger_adapter_class(type(tagger).__name__)
        # tagger_adaptor = TimeTaggerAdaptor(tagger)
        # self._pyroDaemon.register(tagger_adaptor)
        # return tagger_adaptor

    attributes =  {
        'registerMeasurement': registerMeasurement,
        'unregisterMeasurement': unregisterMeasurement,
        'getTagger': getTagger,
    }

    # Iterate over all methods of the object and create proxy methods
    # print('object', class_name)
    for attrib in inspect.classify_class_attrs(Cls):
        if attrib.name in attributes:
            continue
        if attrib.name.startswith('_'):
            continue
        if attrib.name in EXCLUDED_ITERATOR_ATTRIBUTES:
            continue
        if attrib.kind == 'method':
            # print(' --> ', attrib.name)
            attributes[attrib.name] = make_class_attribute_proxy(attrib)

    # Expose class methods with Pyro
    Adaptor = type(Cls.__name__, (TrackedResource,), attributes)
    return Pyro5.api.expose(Adaptor)


def make_timetagger_adapter_class(class_name: str):
    """Generates adapter class for the TimeTagger object.
        The Adapter exposes all public methods except those from exclusion list.
    """

    tagger_class = getattr(TT, class_name)
    assert issubclass(tagger_class, TT.TimeTaggerBase), 'Must be a TT.TimeTaggerBase object.'

    attributes = {}

    # Iterate over all methods of the measurement and create proxy methods
    # print('tagger', class_name)
    for attrib in inspect.classify_class_attrs(tagger_class):
        if attrib.name in EXCLUDED_TAGGER_ATTRIBUTES:
            continue
        if attrib.name.startswith('_'):
            continue
        if attrib.kind == 'method':
            # print(' --> ', attrib.name)
            attributes[attrib.name] = make_class_attribute_proxy(attrib)

    # Expose class methods with Pyro
    TaggerAdapterClass = type(class_name, (TrackedResource,), attributes)
    return Pyro5.api.expose(TaggerAdapterClass)


def make_iterator_constructor(iterator_name: str):
    """Generates a method that constructs the Time Tagger Iterator object and its adaptor.
        The constructor method will be exposed via Pyro and allows creation of the measurements
        and virtual channels via the TimeTaggerRPC interface.
    """

    AdapterClass = make_iterator_adapter_class(iterator_name)
    Iterator = getattr(TT, iterator_name)

    def constructor(self, tagger_proxy, *args, **kwargs):
        tagger_adapter = self._pyroDaemon.proxy2object(tagger_proxy)
        iter = Iterator(tagger_adapter._obj, *args, **kwargs)
        pyro_obj = AdapterClass(iter)
        self._pyroDaemon.register(pyro_obj)
        return pyro_obj
    constructor.__name__ = iterator_name
    constructor.__doc__ = inspect.getdoc(Iterator.__init__)
    constructor.__signature__ = inspect.signature(Iterator.__init__)
    return constructor


def make_synchronized_measurement_constructor():
    """Generates a method that constructs the SynchronizedMeasurements object and its adaptor.
        The constructor method will be exposed via Pyro and allows creation of the measurements
        and virtual channels via the TimeTaggerRPC interface.
    """

    AdapterClass = make_synchronized_measurements_adaptor_class()

    def constructor(self, tagger_proxy):
        tagger_adapter = self._pyroDaemon.proxy2object(tagger_proxy)
        pyro_obj = AdapterClass(tagger_adapter._obj)
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
    TimeTaggerCreator = getattr(TT, 'create'+class_name)

    def constructor(self, *args, **kwargs):
        tagger = TimeTaggerCreator(*args, **kwargs)
        pyro_obj = TimeTaggerAdaptor(tagger)
        self._pyroDaemon.register(pyro_obj)
        return pyro_obj
    constructor.__name__ = TimeTaggerCreator.__name__
    constructor.__doc__ = inspect.getdoc(TimeTaggerCreator)
    constructor.__signature__ = inspect.signature(TimeTaggerCreator)
    return constructor


def make_timetagger_library_adapter():
    """Generates an adapter class for the Time Tagger library and exposes it with Pyro.
        This class is an entry point for remote connections.
    """
    
    class TimeTaggerRPC():
        _enums = {}

        def enum_definitions(self):
            """Enum definitions getter"""
            return self._enums

        def freeTimeTagger(self, tagger_proxy):
            tagger_adapter = self._pyroDaemon.proxy2object(tagger_proxy)
            return TT.freeTimeTagger(tagger_adapter._obj)

    # Create classes
    is_class_or_function = lambda o: inspect.isclass(o) or inspect.isfunction(o)
    for name, Cls in inspect.getmembers(TT, predicate=is_class_or_function):
        if name in EXCLUDED_LIBRARY_MEMBERS:
            continue
        if name.startswith('_'):
            continue
        if hasattr(TimeTaggerRPC, name):
            continue
        if inspect.isfunction(Cls):
            setattr(TimeTaggerRPC, name, make_module_function_proxy(name))
        elif issubclass(Cls, TT.IteratorBase):
            setattr(TimeTaggerRPC, name, make_iterator_constructor(name))
        elif issubclass(Cls, TT.TimeTaggerBase):
            setattr(TimeTaggerRPC, 'create'+name, make_tagger_constructor(name))
        elif issubclass(Cls, TT.SynchronizedMeasurements):
            setattr(TimeTaggerRPC, name, make_synchronized_measurement_constructor())
        elif issubclass(Cls, enum.Enum):
            enum_type = inspect.getmro(Cls)[1]
            enum_values = tuple((e.name, e.value) for e in Cls)
            if len(enum_values) > 0:
                TimeTaggerRPC._enums[name] = (enum_type.__name__, enum_values)
        elif name in ('Resolution', 'CoincidenceTimestamp', 'ChannelEdge'):
            # This case handles older TimeTagger versions that do not use "enum" package.
            if name in TimeTaggerRPC._enums:
                continue
            enum_type = 'IntEnum'  # Use IntEnum for all enums
            enum_values = list()
            for atr in inspect.classify_class_attrs(Cls):
                if not atr.name.startswith('_'):
                    enum_values.append((atr.name, atr.object))
            if len(enum_values) > 0:
                TimeTaggerRPC._enums[name] = (enum_type, tuple(enum_values))

    # Construct and expose the final RPC adapter class
    return Pyro5.api.expose(TimeTaggerRPC)


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
