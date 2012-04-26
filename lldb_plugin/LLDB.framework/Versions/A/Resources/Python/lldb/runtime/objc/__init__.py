__all__ = ["objc_runtime"]
for x in __all__:
    __import__('lldb.runtime.objc.'+x)
