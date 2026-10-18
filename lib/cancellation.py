"""Stopping the file that is running right now.

Two different stops live side by side. "Остановить после файла" lets the
current file finish and drops the rest of the queue; it is a flag checked
between files. "Stop" interrupts the file itself, and that can only work from
inside the long loops - the segment loop of the recogniser, the frame loop of
the writer - so it is a callable those loops ask, and an exception when the
answer is yes.
"""


class Cancelled(Exception):
    """The user pressed Stop while this file was being processed."""


def check(abort):
    """Raises Cancelled when the caller asked to stop. Cheap enough to call
    inside a per-frame loop: it is one function call and a boolean."""
    if abort is not None and abort():
        raise Cancelled()
