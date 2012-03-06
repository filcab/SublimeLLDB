# utilities for the sublime lldb plugin


def debug(thing):
    print thing


def stderr_msg(string):
    if string is not None and len(string) > 0:
        string = 'err> ' + string.replace('\n', '\nerr> ')

    if string[-6:] == '\nerr> ':
        debug('newline at the end')
        string = string[:-5]

    return string


def stdout_msg(string):
    return string
