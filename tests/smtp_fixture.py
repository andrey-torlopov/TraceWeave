#!/usr/bin/env python3
"""Bounded TLS SMTP acceptance fixture, on its test-only Docker network."""
from __future__ import annotations

import argparse
import base64
import hmac
import os
from pathlib import Path
import socket
import socketserver
import ssl
import threading
import uuid

CERTIFICATES = Path('/fixture')
CAPTURE = Path('/capture')
PORT = 2465
MAXIMUM_MESSAGE = 32_768
SLOTS = threading.BoundedSemaphore(4)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def get_request(self):
        raw, address = super().get_request()
        raw.settimeout(20)
        try:
            return self.context.wrap_socket(raw, server_side=True), address
        except (OSError, ssl.SSLError):
            raw.close()
            raise

    def handle_error(self, request, client_address):
        # SMTP bodies and authentication payloads must never reach logs.
        pass


class SMTP(socketserver.StreamRequestHandler):
    def reply(self, value):
        self.wfile.write(value.encode('ascii') + b'\r\n')
        self.wfile.flush()

    def handle(self):
        if not SLOTS.acquire(blocking=False):
            self.reply('421 Fixture busy')
            return
        try:
            self.exchange()
        except (OSError, ValueError):
            pass
        finally:
            SLOTS.release()

    def exchange(self):
        self.reply('220 smtp Synthetic TLS fixture')
        authenticated = False
        recipient = False
        for _ in range(128):
            line = self.rfile.readline(4097)
            if not line or len(line) > 4096 or not line.endswith(b'\r\n'):
                return
            command = line.rstrip(b'\r\n').split(b' ', 1)
            verb = command[0].upper()
            argument = command[1] if len(command) == 2 else b''
            if verb in [b'EHLO', b'HELO']:
                self.reply('250-smtp')
                self.reply('250-AUTH PLAIN')
                self.reply('250 SIZE 32768')
            elif verb == b'AUTH':
                parts = argument.split(b' ', 1)
                if not parts or parts[0].upper() != b'PLAIN':
                    self.reply('504 Unsupported authentication')
                    continue
                payload = parts[1] if len(parts) == 2 else None
                if payload is None:
                    self.reply('334 ')
                    payload = self.rfile.readline(4097).strip()
                try:
                    decoded = base64.b64decode(payload, validate=True).split(b'\0')
                    authenticated = len(decoded) == 3 and hmac.compare_digest(decoded[1], b'synthetic') \
                        and hmac.compare_digest(decoded[2], b'synthetic-smtp-password') \
                        and not (CAPTURE / 'reject').exists()
                except ValueError:
                    authenticated = False
                self.reply('235 Authentication successful' if authenticated else '535 Authentication rejected')
            elif verb == b'QUIT':
                self.reply('221 Bye')
                return
            elif not authenticated:
                self.reply('530 Authentication required')
            elif verb in [b'NOOP', b'RSET']:
                recipient = False
                self.reply('250 OK')
            elif verb == b'MAIL':
                recipient = False
                self.reply('250 OK')
            elif verb == b'RCPT':
                recipient = True
                self.reply('250 OK')
            elif verb == b'DATA' and recipient:
                self.reply('354 End with dot')
                data = bytearray()
                while True:
                    chunk = self.rfile.readline(4097)
                    if not chunk or len(chunk) > 4096:
                        return
                    if chunk == b'.\r\n':
                        break
                    if chunk.startswith(b'..'):
                        chunk = chunk[1:]
                    data.extend(chunk)
                    if len(data) > MAXIMUM_MESSAGE:
                        self.reply('552 Message too large')
                        return
                temporary = CAPTURE / (uuid.uuid4().hex + '.pending')
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'wb') as output:
                    output.write(data)
                    output.flush()
                    os.fsync(output.fileno())
                temporary.rename(temporary.with_suffix('.eml'))
                self.reply('250 Captured')
                recipient = False
            else:
                self.reply('502 Unsupported command')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe', action='store_true')
    args = parser.parse_args()
    if args.probe:
        context = ssl.create_default_context(cafile=str(CERTIFICATES / 'ca.crt'))
        # Readiness covers both certificates used by this synthetic fixture.
        # The backend trusts only ca.crt and must reject the negative-test leaf.
        context.load_verify_locations(cafile=str(CERTIFICATES / 'untrusted.crt'))
        with socket.create_connection(('127.0.0.1', PORT), timeout=2) as raw:
            with context.wrap_socket(raw, server_hostname='smtp') as connection:
                if not connection.recv(1024).startswith(b'220 '):
                    raise SystemExit(1)
        return
    os.umask(0o077)
    CAPTURE.mkdir(parents=True, exist_ok=True, mode=0o700)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(CERTIFICATES / 'smtp.crt'), str(CERTIFICATES / 'smtp.key'))
    with Server(('0.0.0.0', PORT), SMTP) as server:
        server.context = context
        server.serve_forever()


if __name__ == '__main__':
    main()
