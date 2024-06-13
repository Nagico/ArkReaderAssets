import sys

_is_debug = None


def is_debug():
    global _is_debug
    if _is_debug is not None:
        return _is_debug
    gettrace = getattr(sys, 'gettrace', None)
    if gettrace is None:
        _is_debug = False
        return False
    else:
        v = gettrace()
        if v is None:
            _is_debug = False
            return False
        else:
            _is_debug = True
            return True
