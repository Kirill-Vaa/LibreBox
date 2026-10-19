import contextlib
import os
import sys


def main() -> None:
    path, code = sys.argv[1], sys.argv[2]
    temporary = f"{path}.new"
    with contextlib.suppress(FileNotFoundError):
        os.unlink(temporary)

    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        os.write(descriptor, f"{code}\n".encode())
    finally:
        os.close(descriptor)

    os.replace(temporary, path)


if __name__ == "__main__":
    main()
