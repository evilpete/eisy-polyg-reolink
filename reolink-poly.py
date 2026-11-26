#!/usr/bin/env python3
"""
Reolink NVR node server for Polyglot v3 (PG3x on eisy / Polisy).

Subscribes to the NVR's Baichuan TCP push events (port 9000) via the
reolink_aio library and reflects motion / AI detection state on one IoX
node per NVR channel.
"""
import sys

import udi_interface

from nodes import Controller

VERSION = '0.1.0'
LOGGER = udi_interface.LOGGER

if __name__ == '__main__':
    try:
        polyglot = udi_interface.Interface([])
        polyglot.start(VERSION)
        Controller(polyglot, 'nvr', 'nvr', 'Reolink NVR')
        polyglot.runForever()
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)
