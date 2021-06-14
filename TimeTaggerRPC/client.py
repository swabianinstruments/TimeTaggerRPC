
import enum
import Pyro5.api
from . import helper


class TTProxy(Pyro5.api.Proxy):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Load enum definitions and construct enum classes
        definitions = self.enum_definitions()  #
        for name, (enum_type, args) in definitions.items():
            self.__dict__[name] = getattr(enum, enum_type)(name, args)
        self._pyroRelease()


def createProxy(host: str = 'localhost', port: int = 23000, _objectId: str = 'TimeTagger'):
    """Returns Proxy object to the remote Time Tagger RPC

    Args:
        host (str, optional): Server hostname or IP address. Defaults to 'localhost'.
        port (int, optional): Server port. Defaults to 23000.
        _objectId (str, optional): Pyro Object ID. Defaults to 'TimeTagger'.

    Returns:
        Pyro5.api.Proxy: Proxy object to the Time Tagger Library.
    """
    # register native numpy arrays
    helper.register_numpy_handler()

    uri = f"PYRO:{_objectId}@{host}:{port}"
    return TTProxy(uri)
