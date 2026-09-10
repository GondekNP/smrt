#!/usr/bin/env python3
"""A stand-in ACP agent, for testing the proxy without an agent or a container.

It echoes whatever it is given, which is what makes byte-fidelity assertable:
whatever the client sent should come back identical, and any difference is the
proxy's doing.

Modes:

  echo                    echo every line back, verbatim
  stderr-flood <bytes>    write that many bytes to stderr, then echo. More than
                          a pipe buffer's worth, and the proxy must be draining
                          stderr or this blocks forever — which is the point.
  stderr-early            write a SHORT line to stderr, pause, then echo. The
                          pause is what makes buffering visible: a proxy using
                          read() instead of read1() only records this at exit.
  exit <code>             exit immediately, without reading stdin
  half-line               write a frame with no trailing newline, then exit
"""

import sys
import time


def echo() -> None:
    out = sys.stdout.buffer
    inp = sys.stdin.buffer
    while True:
        line = inp.readline()
        if not line:
            return
        out.write(line)
        out.flush()


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "echo"

    if mode == "exit":
        return int(sys.argv[2])

    if mode == "stderr-early":
        sys.stderr.buffer.write(b"starting up\n")
        sys.stderr.buffer.flush()
        time.sleep(0.5)
        echo()
        return 0

    if mode == "stderr-flood":
        sys.stderr.buffer.write(b"noise " * (int(sys.argv[2]) // 6))
        sys.stderr.buffer.flush()
        echo()
        return 0

    if mode == "half-line":
        sys.stdout.buffer.write(b'{"jsonrpc":"2.0","id":1,"result":{}}')
        sys.stdout.buffer.flush()
        return 0

    echo()
    return 0


if __name__ == "__main__":
    sys.exit(main())
