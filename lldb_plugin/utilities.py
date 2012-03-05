# utilities for the sublime lldb plugin

# import root_objects


def stderr_msg(string):
    if string is not None and len(string) > 0:
        string = 'err> ' + string.replace('\n', '\nerr >')
    return string


def stdout_msg(string):
    return string
