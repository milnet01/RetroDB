# =============================================================================
# RETRODB - RetroArch network commands
# =============================================================================
# RetroArch takes plain-text UDP commands while Settings > Network > Network
# Commands is on (network_cmd_enable). Only the local machine is addressed:
# RetroDB launches RetroArch on the machine it runs on.
#
# GET_STATUS is the one command used here that answers, so it doubles as the
# "is RetroArch listening?" probe; DISK_NEXT itself is fire-and-forget.
# DISK_NEXT opens the virtual drive, moves to the next image of the .m3u and
# closes the drive in one step (disk_control_set_index in RetroArch).
# =============================================================================

import socket

RETROARCH_COMMAND_PORT = 55355  # RetroArch's default network_cmd_port


class RetroArchNotListening(Exception):
    """No RetroArch answered on the command port."""


def next_disk(port=RETROARCH_COMMAND_PORT, timeout_s=1.0):
    """Tell the running RetroArch to insert the next disk of its disk list."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout_s)
        # connect() so a closed port fails at once (ConnectionRefusedError)
        # instead of waiting out the timeout.
        sock.connect(('127.0.0.1', port))
        try:
            sock.send(b'GET_STATUS')
            sock.recv(4096)
        except OSError as e:
            raise RetroArchNotListening(str(e)) from e
        sock.send(b'DISK_NEXT')


def send_quit(port):
    """Ask the player on `port` to quit, as its quit key would (PASS-59-64
    §4.6). Fire-and-forget: a closed port or a lost datagram is the
    caller's grace timeout to handle."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.sendto(b'QUIT', ('127.0.0.1', port))
        except OSError:
            pass
