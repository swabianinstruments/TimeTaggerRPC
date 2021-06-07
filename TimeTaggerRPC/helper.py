import base64
import io

import numpy
import Pyro5.api


def save_numpy_array(arr):
    """
    Saves the numpy array in the NPY format for network transmission.
    We avoid the pickle format here for security reasons.
    As Pyro5 does not natively support bytearrays, also encode it as base64.
    """
    output = io.BytesIO()
    numpy.save(output, arr=arr, allow_pickle=False)
    data = base64.b64encode(output.getvalue()).decode('ASCII')
    return {'data': data, '__class__': "numpy.ndarray"}


def load_numpy_array(classname, data):
    assert classname == 'numpy.ndarray'
    buffer = io.BytesIO(base64.b64decode(data['data'].encode('ASCII')))
    arr = numpy.load(buffer, allow_pickle=False)
    return arr


def register_numpy_handler():
    """
    Register numpy.ndarray in Pyro5 for native numpy support.
    This call will mark them as "always stream" instead of "create server side handle".
    """
    Pyro5.api.register_class_to_dict(
        clazz=numpy.ndarray, converter=save_numpy_array)
    Pyro5.api.register_dict_to_class(
        classname='numpy.ndarray', converter=load_numpy_array)
