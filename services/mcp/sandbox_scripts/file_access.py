import errno
import os
import stat
import sys


def open_regular(path: str) -> int:
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise OSError(errno.EINVAL, "Not a regular file", path)

    return descriptor


def open_regular_or_exit(path: str) -> int:
    try:
        return open_regular(path)
    except OSError as error:
        sys.exit(f"{path}: {error.strerror}")
