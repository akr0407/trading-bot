"""
numba mock — Provides no-op JIT decorators so pandas_ta imports cleanly
without the real numba package (which has DLL/version issues on Python 3.14).

This mock is transparent: decorated functions run as plain Python.
Performance impact is negligible for a polling bot that calculates
indicators once every few minutes.
"""


def njit(*args, **kwargs):
    """Mock @njit decorator — returns the function unchanged."""
    def decorator(func):
        return func
    if len(args) == 1 and callable(args[0]):
        return args[0]
    return decorator


def jit(*args, **kwargs):
    """Mock @jit decorator — returns the function unchanged."""
    def decorator(func):
        return func
    if len(args) == 1 and callable(args[0]):
        return args[0]
    return decorator


def generated_jit(*args, **kwargs):
    """Mock @generated_jit decorator."""
    def decorator(func):
        return func
    if len(args) == 1 and callable(args[0]):
        return args[0]
    return decorator


def vectorize(*args, **kwargs):
    """Mock @vectorize decorator."""
    def decorator(func):
        return func
    if len(args) == 1 and callable(args[0]):
        return args[0]
    return decorator


def guvectorize(*args, **kwargs):
    """Mock @guvectorize decorator."""
    def decorator(func):
        return func
    if len(args) == 1 and callable(args[0]):
        return args[0]
    return decorator


# Type stubs that pandas_ta might reference
def typeof_impl(*args, **kwargs):
    pass


class types:
    """Mock numba.types module."""
    int32 = int
    int64 = int
    float32 = float
    float64 = float
    boolean = bool
    void = None
    Array = None
    unicode_type = str

    @staticmethod
    def FunctionType(*args, **kwargs):
        return None


class core:
    class types:
        int32 = int
        int64 = int
        float32 = float
        float64 = float

    class typing:
        class typeof:
            @staticmethod
            def typeof(*args, **kwargs):
                return None


def prange(*args, **kwargs):
    """Mock prange — falls back to regular range."""
    return range(*args)
