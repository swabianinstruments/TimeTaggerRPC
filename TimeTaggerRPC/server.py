import inspect
import logging
import enum
import uuid

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

logger = logging.getLogger('TimeTaggerRPC.server')


class TrackedResource:
    """Implements 'close' method that clears the underlying object.
        This class is not exposed by the Pyro and therefore its methods do
        not appear on the client proxy.
    """
    _obj: object
    _id: str

    def __init__(self, obj):
        self._obj = obj
        self._id = type(self).__name__ + "_" + uuid.uuid4().hex
        self._logger = logger.getChild(type(self).__name__)
        self._logger.debug('New adapter instance: %s', self)
        Pyro5.api.current_context.track_resource(self)

    def __repr__(self) -> str:
        return '<' + self._id + '>'

    def close(self):
        self._logger.debug('Closed: %s', self)
        try:
            if isinstance(self._obj, TT.TimeTaggerBase):
                TT.freeTimeTagger(self._obj)
        except AttributeError as e:
            self._logger.debug(e)
        finally:
            self._obj = None
        Pyro5.api.current_context.untrack_resource(self)
        if hasattr(self, '_pyroDaemon'):
            self._pyroDaemon.unregister(self)


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
        def fget(self): return getattr(self._obj, attrib.name)
        def fset(self, value): setattr(self._obj, attrib.name, value)
        def fdel(self): delattr(self._obj, attrib.name)
        doc = inspect.getdoc(attrib.object)
        return property(fget, fset, fdel, doc)
    else:
        raise ValueError('Unknown attribute kind %s', attrib.kind)


def make_data_object_adaptor_class(class_name):
    """Generates adaptor class for DataObject returned by Iterator.getDataObject()."""

    logger.debug('Constructing adaptor for "%s"', class_name)
    assert class_name.endswith('Data'), 'Must be a DataObject object.'
    TTClass = getattr(TT, class_name)

    def discard(self):
        """Discard server-side object explicitly"""
        self.close()

    attributes = {'discard': discard}

    # Iterate over all methods of the measurement and create proxy methods
    for attrib in inspect.classify_class_attrs(TTClass):
        if attrib.name.startswith('_'):
            continue
        if attrib.name.startswith('this'):
            continue
        logger.debug('|-> (%s) %s.%s', attrib.kind, class_name, attrib.name)
        attributes[attrib.name] = make_class_attribute_proxy(attrib)

    # Expose class methods with Pyro
    DataObjectAdapter = type(class_name, (TrackedResource,), attributes)
    return Pyro5.api.expose(DataObjectAdapter)


def make_iterator_adapter_class(class_name: str):
    """Generates adapter class for the given Time Tagger iterator class
        and exposes them with Pyro.
    """
    logger.debug('Constructing adaptor for "%s"', class_name)
    iterator_class = getattr(TT, class_name)
    assert issubclass(iterator_class, TT.IteratorBase), 'Must be a TT.Iterator object.'

    attributes = {}

    if hasattr(iterator_class, 'getDataObject'):
        def getDataObject(self, *args, **kwargs):
            data_obj = self._obj.getDataObject(*args, **kwargs)
            pyro_obj = self._DataObjectAdapter(data_obj)
            self._pyroDaemon.register(pyro_obj, pyro_obj._id)
            return pyro_obj
        getDataObject.__doc__ = inspect.getdoc(iterator_class.getDataObject)
        getDataObject.__signature__ = inspect.signature(iterator_class.getDataObject)
        attributes['_DataObjectAdapter'] = make_data_object_adaptor_class(class_name+'Data')
        attributes['getDataObject'] = getDataObject

    # Iterate over all methods of the measurement and create proxy methods
    for attrib in inspect.classify_class_attrs(iterator_class):
        if attrib.name in attributes:
            logger.debug('|-> (%s) %s.%s \t=> ALREADY EXISTS', attrib.kind, class_name, attrib.name)
            continue
        if attrib.name in EXCLUDED_ITERATOR_ATTRIBUTES:
            logger.debug('|-> (%s) %s.%s \t=> SKIPPED', attrib.kind, class_name, attrib.name)
            continue
        if attrib.name.startswith('_'):
            continue
        if attrib.kind == 'method':
            logger.debug('|-> (%s) %s.%s', attrib.kind, class_name, attrib.name)
            attributes[attrib.name] = make_class_attribute_proxy(attrib)

    # Expose class methods with Pyro
    IteratorAdapter = type(class_name, (TrackedResource,), attributes)
    return Pyro5.api.expose(IteratorAdapter)


def make_synchronized_measurements_adaptor_class():
    """Generates adapter class for the given Time Tagger iterator class
        and exposes them with Pyro.
    """
    Cls = TT.SynchronizedMeasurements
    class_name = Cls.__name__
    logger.debug('Constructing adaptor for "%s"', class_name)
    TimeTaggerBaseAdaptor = make_timetagger_adapter_class('TimeTaggerBase')

    def registerMeasurement(self, measurement_proxy):
        iterator_adaptor = self._pyroDaemon.proxy2object(measurement_proxy)
        self._logger.debug('registerMeasurement(%s)', type(iterator_adaptor).__name__)
        return self._obj.registerMeasurement(iterator_adaptor._obj)

    def unregisterMeasurement(self, measurement_proxy):
        iterator_adaptor = self._pyroDaemon.proxy2object(measurement_proxy)
        self._logger.debug('unregisterMeasurement(%s)', type(iterator_adaptor).__name__)
        return self._obj.unregisterMeasurement(iterator_adaptor._obj)

    def getTagger(self):
        # Construct Time Tagger adaptor instance only once.
        if not hasattr(self, '_ttb_adaptor'):
            tagger = self._obj.getTagger()
            self._ttb_adaptor = TimeTaggerBaseAdaptor(tagger)
            self._pyroDaemon.register(self._ttb_adaptor, self._ttb_adaptor._id)
        return self._ttb_adaptor

    attributes = {
        'registerMeasurement': registerMeasurement,
        'unregisterMeasurement': unregisterMeasurement,
        'getTagger': getTagger,
    }

    # Iterate over all methods of the object and create proxy methods
    for attrib in inspect.classify_class_attrs(Cls):
        if attrib.name in attributes:
            logger.debug('|-> (%s) %s.%s \t=> ALREADY EXISTS', attrib.kind, class_name, attrib.name)
            continue
        if attrib.name.startswith('_'):
            continue
        if attrib.name in EXCLUDED_ITERATOR_ATTRIBUTES:
            logger.debug('|-> (%s) %s.%s \t=> SKIPPED', attrib.kind, class_name, attrib.name)
            continue
        if attrib.kind == 'method':
            logger.debug('|-> (%s) %s.%s', attrib.kind, class_name, attrib.name)
            attributes[attrib.name] = make_class_attribute_proxy(attrib)

    # Expose class methods with Pyro
    Adaptor = type(class_name, (TrackedResource,), attributes)
    return Pyro5.api.expose(Adaptor)


def make_timetagger_adapter_class(class_name: str):
    """Generates adapter class for the TimeTagger object.
        The Adapter exposes all public methods except those from exclusion list.
    """

    logger.debug('Constructing adaptor for "%s"', class_name)
    tagger_class = getattr(TT, class_name)
    assert issubclass(tagger_class, TT.TimeTaggerBase), 'Must be a TT.TimeTaggerBase object.'

    attributes = {}

    # Iterate over all methods of the measurement and create proxy methods
    for attrib in inspect.classify_class_attrs(tagger_class):
        if attrib.name in EXCLUDED_TAGGER_ATTRIBUTES:
            logger.debug('|-> (%s) %s.%s \t=> SKIPPED', attrib.kind, class_name, attrib.name)
            continue
        if attrib.name.startswith('_'):
            continue
        if attrib.kind == 'method':
            logger.debug('|-> (%s) %s.%s', attrib.kind, class_name, attrib.name)
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
        self._pyroDaemon.register(pyro_obj, pyro_obj._id)
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
        tt_obj = TT.SynchronizedMeasurements(tagger_adapter._obj)
        pyro_obj = AdapterClass(tt_obj)
        self._pyroDaemon.register(pyro_obj, pyro_obj._id)
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
        self._pyroDaemon.register(pyro_obj, pyro_obj._id)
        return pyro_obj
    constructor.__name__ = TimeTaggerCreator.__name__
    constructor.__doc__ = inspect.getdoc(TimeTaggerCreator)
    constructor.__signature__ = inspect.signature(TimeTaggerCreator)
    return constructor


def make_timetagger_library_adapter():
    """Generates an adapter class for the Time Tagger library and exposes it with Pyro.
        This class is an entry point for remote connections.
    """
    logger.debug('Generating TimeTagger library adaptor class.')

    def freeTimeTagger(self, tagger_proxy):
        tagger_adapter = self._pyroDaemon.proxy2object(tagger_proxy)
        return TT.freeTimeTagger(tagger_adapter._obj)

    def enum_definitions(self):
        return self._enums

    attributes = {
        '_enums': {},  # Class attribute
        'enum_definitions': enum_definitions,
        'freeTimeTagger': freeTimeTagger,
    }

    def is_class_or_function(o):
        return inspect.isclass(o) or inspect.isfunction(o)

    # Create classes
    for name, Cls in inspect.getmembers(TT, predicate=is_class_or_function):
        if name in EXCLUDED_LIBRARY_MEMBERS or name.startswith('_'):
            logger.debug('|-> TimeTaggerRPC.%s \t=> SKIPPED', name)
            continue
        if name in attributes:
            logger.debug('|-> TimeTaggerRPC.%s \t=> ALREADY EXISTS', name)
            continue
        if inspect.isfunction(Cls):
            attributes[name] = make_module_function_proxy(name)
        elif issubclass(Cls, TT.IteratorBase):
            attributes[name] = make_iterator_constructor(name)
        elif issubclass(Cls, TT.TimeTaggerBase):
            attributes['create'+name] = make_tagger_constructor(name)
        elif issubclass(Cls, TT.SynchronizedMeasurements):
            attributes[name] = make_synchronized_measurement_constructor()
        elif issubclass(Cls, enum.Enum):
            enum_type = inspect.getmro(Cls)[1]
            enum_values = tuple((e.name, e.value) for e in Cls)
            if len(enum_values) > 0:
                attributes['_enums'][name] = (enum_type.__name__, enum_values)
        elif name in ('Resolution', 'CoincidenceTimestamp', 'ChannelEdge'):
            # This case handles older TimeTagger versions that do not use "enum" package.
            if name in attributes['_enums']:
                continue
            enum_type = 'IntEnum'  # Use IntEnum for all enums
            enum_values = list()
            for atr in inspect.classify_class_attrs(Cls):
                if not atr.name.startswith('_'):
                    enum_values.append((atr.name, atr.object))
            if len(enum_values) > 0:
                attributes['_enums'][name] = (enum_type, tuple(enum_values))

    # Construct and expose the final RPC adapter class
    TimeTaggerRPC = type('TimeTaggerRPC', (object,), attributes)
    logger.debug('Generating TimeTagger library adaptor completed.')
    return Pyro5.api.expose(TimeTaggerRPC)


def start_server(host='localhost', port=23000, use_ns=False, start_ns=False, verbose=False):
    """This method starts the Pyro server eventloop and processes client requests."""

    if verbose:
        logging.basicConfig(level=logging.DEBUG)

    # Start Pyro nameserver in a subprocess
    if start_ns:
        import subprocess
        import sys
        logger.info('Starting Pyro nameserver')
        ns_proc = subprocess.Popen(
            [sys.executable, '-m', 'Pyro5.nameserver', '-n', host])

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
            uri = daemon.register(rpc_obj, 'TimeTaggerRPC')
            print('Server URI=', uri)
            if use_ns:
                ns = Pyro5.api.locate_ns()         # find the name server
                # register the object with a name in the name server
                ns.register("TimeTaggerRPC", uri)
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
    parser.add_argument(
        '-v,--verbose', dest='verbose', action='store_true',
        help='Enable log messages at DEBUG level.'
    )

    args = parser.parse_args()

    start_server(**vars(args))


if __name__ == "__main__":
    main()
