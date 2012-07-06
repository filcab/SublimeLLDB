import sys
import threading

from multiprocessing import Lock

DFILE = sys.__stderr__
_active = 0

debugAny = 0  # Prints the message regardless of debug level.
debugVerbose = 1 << 0
debugViews = 1 << 1
debugMonitors = 1 << 2
debugLLDB = 1 << 3
debugDriver = 1 << 4
debugRoot = 1 << 5
debugPlugin = 1 << 6
debugSettings = 1 << 7

debugAll = 0xff

# Mutex to lock our debug function.
mutex = Lock()


def debug(level, thing):
    if _active & level == level:
        with mutex:
            print >> DFILE, threading.current_thread().name, str(thing)


def toggle_debug(level):
    global _active
    _active = _active ^ level


def set_debug(level):
    global _active
    _active = _active | level


def unset_debug(level):
    global _active
    _active = _active & (~ level)


def clear_debug():
    global _active
    _active = 0
