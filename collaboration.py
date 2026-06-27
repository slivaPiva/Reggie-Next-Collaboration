import base64
import json
import queue
import random
import socket
import struct
import subprocess
import threading
import time
import urllib.parse
import urllib.error
import urllib.request
import uuid
import xml.etree.ElementTree as ET

from PyQt6 import QtCore


class _TraversalPeerConnection(object):
    MAGIC = b"RNC1"
    TYPE_OPEN = 1
    TYPE_OPEN_ACK = 2
    TYPE_DATA = 3
    TYPE_DATA_ACK = 4
    TYPE_CLOSE = 5
    TYPE_KEEPALIVE = 6
    MAX_FRAGMENT_SIZE = 1024
    RESEND_INTERVAL = 0.45
    KEEPALIVE_INTERVAL = 4.0
    MAX_RETRIES = 30

    def __init__(self, endpoint, token, remote_addr=None, initiator=False):
        self.endpoint = endpoint
        self.token = bytes(token)
        self.remote_addr = remote_addr
        self.initiator = bool(initiator)
        self.conn_id = None
        self._send_queue = queue.Queue()
        self._pending = {}
        self._pending_lock = threading.Lock()
        self._next_send_message_id = 1
        self._next_recv_message_id = 1
        self._received_complete = {}
        self._received_fragments = {}
        self._recv_lock = threading.Lock()
        self._open_event = threading.Event()
        self._closed = False
        self._error = ""
        self._last_activity = time.monotonic()
        self._last_open_send = 0.0
        self._open_attempts = 0

    @classmethod
    def build_open_packet(cls, token):
        return struct.pack("!4sB8s", cls.MAGIC, cls.TYPE_OPEN, bytes(token))

    @classmethod
    def parse_packet(cls, data):
        if len(data) < 13:
            return None
        magic, packet_type, token = struct.unpack("!4sB8s", data[:13])
        if magic != cls.MAGIC:
            return None
        if packet_type in (cls.TYPE_OPEN, cls.TYPE_OPEN_ACK, cls.TYPE_CLOSE, cls.TYPE_KEEPALIVE):
            return {
                "type": packet_type,
                "token": token,
            }
        if packet_type == cls.TYPE_DATA_ACK:
            if len(data) < 17:
                return None
            msg_id = struct.unpack("!I", data[13:17])[0]
            return {
                "type": packet_type,
                "token": token,
                "msg_id": msg_id,
            }
        if packet_type == cls.TYPE_DATA:
            if len(data) < 21:
                return None
            msg_id, frag_index, frag_count = struct.unpack("!IHH", data[13:21])
            return {
                "type": packet_type,
                "token": token,
                "msg_id": msg_id,
                "frag_index": frag_index,
                "frag_count": frag_count,
                "payload": data[21:],
            }
        return None

    def assign_connection(self, conn_id):
        self.conn_id = conn_id

    def wait_until_open(self, timeout):
        self._open_event.wait(float(timeout))
        return self.is_open and not self._closed

    @property
    def is_open(self):
        return self._open_event.is_set()

    @property
    def error(self):
        return str(self._error or "")

    def update_remote_addr(self, remote_addr):
        self.remote_addr = remote_addr

    def send_line(self, data):
        if self._closed:
            raise OSError(self.error or "Traversal peer is closed")
        self._send_queue.put(bytes(data))

    def shutdown(self):
        if self._closed:
            return
        self._closed = True
        if self.remote_addr and self.is_open:
            self.endpoint.send_peer_packet(
                self.remote_addr,
                struct.pack("!4sB8s", self.MAGIC, self.TYPE_CLOSE, self.token),
            )
        self.endpoint.remove_peer(self)

    def fail(self, message):
        self._error = str(message or "Traversal peer failed")
        self._closed = True
        self._open_event.set()
        self.endpoint.remove_peer(self)

    def _send_open(self, now):
        if self._closed or (not self.remote_addr):
            return
        if (now - self._last_open_send) < self.RESEND_INTERVAL:
            return
        self._last_open_send = now
        self._open_attempts += 1
        if self._open_attempts > self.MAX_RETRIES:
            self.fail("Timed out opening the traversal proxy")
            self.endpoint.notify_peer_failure(self)
            return
        self.endpoint.send_peer_packet(self.remote_addr, self.build_open_packet(self.token))

    def _send_ack(self, msg_id):
        if not self.remote_addr:
            return
        packet = struct.pack("!4sB8sI", self.MAGIC, self.TYPE_DATA_ACK, self.token, int(msg_id))
        self.endpoint.send_peer_packet(self.remote_addr, packet)

    def _enqueue_message(self, payload):
        fragments = []
        start = 0
        while start < len(payload):
            fragments.append(payload[start:start + self.MAX_FRAGMENT_SIZE])
            start += self.MAX_FRAGMENT_SIZE
        if not fragments:
            fragments = [b""]
        with self._pending_lock:
            msg_id = self._next_send_message_id
            self._next_send_message_id += 1
            self._pending[msg_id] = {
                "fragments": fragments,
                "tries": 0,
                "last_send": 0.0,
            }

    def _send_pending_messages(self, now):
        with self._pending_lock:
            pending_items = list(self._pending.items())
        for msg_id, info in pending_items:
            if info["last_send"] and (now - info["last_send"]) < self.RESEND_INTERVAL:
                continue
            if info["tries"] >= self.MAX_RETRIES:
                self.fail("Traversal proxy timed out waiting for packet acknowledgement")
                self.endpoint.notify_peer_failure(self)
                return
            fragments = info["fragments"]
            frag_count = len(fragments)
            for frag_index, fragment in enumerate(fragments):
                packet = struct.pack(
                    "!4sB8sIHH",
                    self.MAGIC,
                    self.TYPE_DATA,
                    self.token,
                    int(msg_id),
                    int(frag_index),
                    int(frag_count),
                ) + fragment
                self.endpoint.send_peer_packet(self.remote_addr, packet)
            info["tries"] += 1
            info["last_send"] = now

    def pump(self, now):
        if self._closed:
            return
        while True:
            try:
                payload = self._send_queue.get_nowait()
            except queue.Empty:
                break
            self._enqueue_message(payload)
        if self.initiator and not self.is_open:
            self._send_open(now)
            return
        if not self.is_open:
            return
        self._send_pending_messages(now)
        if self.remote_addr and (now - self._last_activity) >= self.KEEPALIVE_INTERVAL:
            self.endpoint.send_peer_packet(
                self.remote_addr,
                struct.pack("!4sB8s", self.MAGIC, self.TYPE_KEEPALIVE, self.token),
            )
            self._last_activity = now

    def handle_packet(self, packet):
        if self._closed:
            return
        packet_type = int(packet.get("type", 0))
        self._last_activity = time.monotonic()

        if packet_type == self.TYPE_OPEN:
            self._open_event.set()
            if self.remote_addr:
                self.endpoint.send_peer_packet(
                    self.remote_addr,
                    struct.pack("!4sB8s", self.MAGIC, self.TYPE_OPEN_ACK, self.token),
                )
            return

        if packet_type == self.TYPE_OPEN_ACK:
            self._open_event.set()
            return

        if packet_type == self.TYPE_CLOSE:
            self._closed = True
            self.endpoint.notify_peer_closed(self)
            return

        if packet_type == self.TYPE_KEEPALIVE:
            self._open_event.set()
            return

        if packet_type == self.TYPE_DATA_ACK:
            with self._pending_lock:
                self._pending.pop(int(packet.get("msg_id", 0)), None)
            self._open_event.set()
            return

        if packet_type != self.TYPE_DATA:
            return

        self._open_event.set()
        msg_id = int(packet.get("msg_id", 0))
        frag_index = int(packet.get("frag_index", 0))
        frag_count = int(packet.get("frag_count", 0))
        payload = bytes(packet.get("payload", b""))
        if msg_id <= 0 or frag_count <= 0 or frag_index < 0 or frag_index >= frag_count:
            return

        with self._recv_lock:
            if msg_id < self._next_recv_message_id:
                self._send_ack(msg_id)
                return
            if msg_id in self._received_complete:
                self._send_ack(msg_id)
                return
            message_info = self._received_fragments.setdefault(msg_id, {
                "count": frag_count,
                "fragments": {},
            })
            if message_info["count"] != frag_count:
                return
            message_info["fragments"][frag_index] = payload
            if len(message_info["fragments"]) == frag_count:
                assembled = b"".join(
                    message_info["fragments"].get(index, b"")
                    for index in range(frag_count)
                )
                self._received_complete[msg_id] = assembled
                self._received_fragments.pop(msg_id, None)
                self._send_ack(msg_id)

            ready_payloads = []
            while self._next_recv_message_id in self._received_complete:
                ready_payloads.append(self._received_complete.pop(self._next_recv_message_id))
                self._next_recv_message_id += 1

        for item in ready_payloads:
            self.endpoint.deliver_peer_message(self, item)


class _DolphinTraversalEndpoint(object):
    TRAVERSAL_SERVER = "stun.dolphin-emu.org"
    TRAVERSAL_PORT = 6262
    TRAVERSAL_PORT_ALT = 6226
    TRAVERSAL_PROTO_VERSION = 0
    PACKET_SIZE = 37
    PACKET_ACK = 0
    PACKET_PING = 1
    PACKET_HELLO_FROM_CLIENT = 2
    PACKET_HELLO_FROM_SERVER = 3
    PACKET_CONNECT_PLEASE = 4
    PACKET_PLEASE_SEND_PACKET = 5
    PACKET_CONNECT_READY = 6
    PACKET_CONNECT_FAILED = 7
    PACKET_TEST_PLEASE = 8
    CONNECT_FAILED_CLIENT_DIDNT_RESPOND = 0
    CONNECT_FAILED_CLIENT_FAILURE = 1
    CONNECT_FAILED_NO_SUCH_CLIENT = 2
    RESEND_INTERVAL = 0.30
    MAX_RETRIES = 20
    PING_INTERVAL = 0.5

    def __init__(self, manager, bind_port=0, host_mode=False):
        self.manager = manager
        self.bind_port = int(bind_port or 0)
        self.host_mode = bool(host_mode)
        self._sock = None
        self._thread = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._server_addr = None
        self._server_alt_addr = None
        self._host_code = ""
        self._external_address = None
        self._hello_event = threading.Event()
        self._failure_message = ""
        self._last_ping_time = 0.0
        self._pending_traversal = {}
        self._connect_requests = {}
        self._peers_by_token = {}
        self._peers_by_addr = {}

    @staticmethod
    def _pack_ipv4_word(ip):
        return struct.unpack("<I", socket.inet_aton(ip))[0]

    @staticmethod
    def _unpack_ipv4_word(word):
        return socket.inet_ntoa(struct.pack("<I", int(word)))

    @classmethod
    def _pack_traversal_packet(cls, packet_type, request_id, payload):
        body = bytes(payload[:28]).ljust(28, b"\x00")
        return struct.pack("<BQ", int(packet_type), int(request_id) & 0xFFFFFFFFFFFFFFFF) + body

    @classmethod
    def _unpack_traversal_packet(cls, data):
        if len(data) < cls.PACKET_SIZE:
            return None
        packet_type, request_id = struct.unpack("<BQ", data[:9])
        return packet_type, request_id, data[9:37]

    @classmethod
    def _parse_traversal_address(cls, payload):
        if len(payload) < 19:
            return None
        is_ipv6 = struct.unpack("<B", payload[:1])[0]
        words = struct.unpack("<IIII", payload[1:17])
        port_raw = struct.unpack("<H", payload[17:19])[0]
        if is_ipv6:
            return None
        try:
            ip = cls._unpack_ipv4_word(words[0])
        except OSError:
            return None
        return ip, socket.ntohs(port_raw)

    @staticmethod
    def _make_request_id():
        return random.getrandbits(64)

    @staticmethod
    def _make_peer_token():
        return struct.pack("!Q", random.getrandbits(64))

    def local_port(self):
        if self._sock is None:
            return 0
        try:
            return int(self._sock.getsockname()[1])
        except Exception:
            return 0

    def host_code(self):
        return str(self._host_code or "")

    def failure_message(self):
        return str(self._failure_message or "")

    def start(self, timeout=8.0):
        self._failure_message = ""
        self._stop_event.clear()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("0.0.0.0", self.bind_port))
        self._sock.settimeout(0.1)
        self._resolve_server_addresses()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        payload = struct.pack("<B", self.TRAVERSAL_PROTO_VERSION)
        self._send_traversal_packet(self.PACKET_HELLO_FROM_CLIENT, payload, track=True)
        if not self._hello_event.wait(float(timeout)):
            message = self.failure_message() or "Traversal server did not respond in time"
            self.stop()
            raise OSError(message)
        return self.host_code()

    def stop(self):
        self._stop_event.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            try:
                thread.join(timeout=0.2)
            except RuntimeError:
                pass
        with self._lock:
            peers = list(self._peers_by_token.values())
            self._peers_by_token.clear()
            self._peers_by_addr.clear()
            self._pending_traversal.clear()
            self._connect_requests.clear()
        for peer in peers:
            peer.fail("Traversal endpoint stopped")

    def _resolve_server_addresses(self):
        infos = socket.getaddrinfo(
            self.TRAVERSAL_SERVER,
            self.TRAVERSAL_PORT,
            socket.AF_INET,
            socket.SOCK_DGRAM,
        )
        if not infos:
            raise OSError("Unable to resolve the Dolphin traversal server")
        self._server_addr = infos[0][4]
        self._server_alt_addr = (self._server_addr[0], self.TRAVERSAL_PORT_ALT)

    def _send_raw(self, addr, payload):
        if self._sock is None:
            raise OSError("Traversal socket is closed")
        self._sock.sendto(payload, addr)

    def _send_traversal_packet(self, packet_type, payload, request_id=None, track=False):
        if request_id is None:
            request_id = self._make_request_id()
        packet = self._pack_traversal_packet(packet_type, request_id, payload)
        self._send_raw(self._server_addr, packet)
        if track:
            with self._lock:
                self._pending_traversal[request_id] = {
                    "packet_type": int(packet_type),
                    "payload": bytes(payload),
                    "tries": 1,
                    "last_send": time.monotonic(),
                }
        return request_id

    def _send_traversal_ack(self, request_id, ok=True):
        payload = struct.pack("<B", 1 if ok else 0)
        packet = self._pack_traversal_packet(self.PACKET_ACK, request_id, payload)
        try:
            self._send_raw(self._server_addr, packet)
        except OSError:
            pass

    def _send_traversal_ping(self):
        if not self._host_code:
            return
        payload = self.host_code().encode("ascii", "ignore")[:8].ljust(8, b"\x00")
        try:
            self._send_traversal_packet(self.PACKET_PING, payload, track=False)
        except OSError:
            pass

    def send_peer_packet(self, addr, payload):
        if (self._sock is None) or (not addr):
            return
        try:
            self._sock.sendto(payload, addr)
        except OSError:
            return

    def remove_peer(self, peer):
        with self._lock:
            current = self._peers_by_token.get(peer.token)
            if current is peer:
                self._peers_by_token.pop(peer.token, None)
            if peer.remote_addr:
                current = self._peers_by_addr.get(peer.remote_addr)
                if current is peer:
                    self._peers_by_addr.pop(peer.remote_addr, None)
            for request_id, pending_peer in list(self._connect_requests.items()):
                if pending_peer is peer:
                    self._connect_requests.pop(request_id, None)

    def _add_peer(self, peer):
        with self._lock:
            self._peers_by_token[peer.token] = peer
            if peer.remote_addr:
                self._peers_by_addr[peer.remote_addr] = peer

    def _lookup_peer(self, token, addr):
        with self._lock:
            peer = self._peers_by_token.get(token)
            if peer is not None:
                return peer
            return self._peers_by_addr.get(addr)

    def _create_host_peer(self, token, addr):
        peer = _TraversalPeerConnection(self, token, remote_addr=addr, initiator=False)
        self._add_peer(peer)
        self.manager._attach_traversal_peer(peer, addr)
        return peer

    def connect_to_host_code(self, host_code, timeout=15.0):
        host_code = str(host_code or "").strip().lower()
        if len(host_code) != 8:
            raise OSError("Invalid Dolphin host code")
        payload = host_code.encode("ascii", "ignore")[:8].ljust(8, b"\x00")
        peer = _TraversalPeerConnection(self, self._make_peer_token(), initiator=True)
        self._add_peer(peer)
        request_id = self._send_traversal_packet(self.PACKET_CONNECT_PLEASE, payload, track=True)
        with self._lock:
            self._connect_requests[request_id] = peer
        if not peer.wait_until_open(float(timeout)):
            error_text = peer.error or "Traversal proxy timed out connecting to the host"
            self.remove_peer(peer)
            raise OSError(error_text)
        return peer

    def deliver_peer_message(self, peer, payload):
        if peer.conn_id is None:
            return
        self.manager._handle_received_line(peer.conn_id, payload)

    def notify_peer_failure(self, peer):
        if peer.conn_id is not None:
            self.manager._drop_connection(peer.conn_id)

    def notify_peer_closed(self, peer):
        if peer.conn_id is not None:
            self.manager._drop_connection(peer.conn_id)

    def _handle_connect_ready(self, request_id, remote_addr):
        with self._lock:
            peer = self._connect_requests.pop(request_id, None)
        if peer is None:
            return
        peer.update_remote_addr(remote_addr)
        self._add_peer(peer)

    def _handle_connect_failed(self, request_id, reason_code):
        with self._lock:
            peer = self._connect_requests.pop(request_id, None)
        if peer is None:
            return
        if reason_code == self.CONNECT_FAILED_NO_SUCH_CLIENT:
            message = "Traversal server could not find the host"
        elif reason_code == self.CONNECT_FAILED_CLIENT_FAILURE:
            message = "Traversal server could not open a connection to the host"
        else:
            message = "Traversal server timed out connecting to the host"
        peer.fail(message)

    def _handle_traversal_packet(self, packet_type, request_id, payload):
        if packet_type == self.PACKET_ACK:
            ack_ok = bool(struct.unpack("<B", payload[:1] or b"\x00")[0])
            with self._lock:
                pending = self._pending_traversal.pop(request_id, None)
            if pending is not None and (not ack_ok):
                self._failure_message = "Traversal server rejected a packet"
            return

        if packet_type == self.PACKET_HELLO_FROM_SERVER:
            ok = bool(struct.unpack("<B", payload[:1] or b"\x00")[0])
            self._send_traversal_ack(request_id, ok=ok)
            if not ok:
                self._failure_message = "The Dolphin traversal server rejected this protocol version"
                self._hello_event.set()
                return
            self._host_code = payload[1:9].decode("ascii", "ignore").rstrip("\x00")
            self._external_address = self._parse_traversal_address(payload[9:28])
            self._hello_event.set()
            return

        if packet_type == self.PACKET_PLEASE_SEND_PACKET:
            self._send_traversal_ack(request_id, ok=True)
            remote_addr = self._parse_traversal_address(payload[:19])
            if remote_addr:
                probe = b"Hello from Dolphin Netplay..."
                self.send_peer_packet(remote_addr, probe)
            return

        if packet_type == self.PACKET_CONNECT_READY:
            self._send_traversal_ack(request_id, ok=True)
            original_request_id = struct.unpack("<Q", payload[:8])[0]
            remote_addr = self._parse_traversal_address(payload[8:27])
            if remote_addr:
                self._handle_connect_ready(original_request_id, remote_addr)
            return

        if packet_type == self.PACKET_CONNECT_FAILED:
            self._send_traversal_ack(request_id, ok=True)
            original_request_id = struct.unpack("<Q", payload[:8])[0]
            reason_code = struct.unpack("<B", payload[8:9] or b"\x00")[0]
            self._handle_connect_failed(original_request_id, reason_code)
            return

        self._send_traversal_ack(request_id, ok=True)

    def _handle_peer_packet(self, data, addr):
        packet = _TraversalPeerConnection.parse_packet(data)
        if packet is None:
            if self.host_mode:
                self.manager._handle_discovery_packet(data, addr, self._sock)
            return
        token = packet["token"]
        peer = self._lookup_peer(token, addr)
        if peer is None:
            if self.host_mode and int(packet.get("type", 0)) == _TraversalPeerConnection.TYPE_OPEN:
                peer = self._create_host_peer(token, addr)
            else:
                return
        if peer.remote_addr is None:
            peer.update_remote_addr(addr)
            self._add_peer(peer)
        peer.handle_packet(packet)

    def _resend_traversal_packets(self, now):
        failures = []
        with self._lock:
            items = list(self._pending_traversal.items())
        for request_id, info in items:
            interval = min(self.RESEND_INTERVAL * max(1, int(info.get("tries", 1))), 1.5)
            if (now - info["last_send"]) < interval:
                continue
            if info["tries"] >= self.MAX_RETRIES:
                failures.append((request_id, info))
                continue
            try:
                packet = self._pack_traversal_packet(info["packet_type"], request_id, info["payload"])
                self._send_raw(self._server_addr, packet)
            except OSError:
                failures.append((request_id, info))
                continue
            info["tries"] += 1
            info["last_send"] = now
        if not failures:
            return
        with self._lock:
            for request_id, info in failures:
                self._pending_traversal.pop(request_id, None)
                peer = self._connect_requests.pop(request_id, None)
                if peer is not None:
                    peer.fail("Traversal server timed out connecting to the host")
                elif info["packet_type"] == self.PACKET_HELLO_FROM_CLIENT:
                    self._failure_message = "Traversal server timed out during registration"
                    self._hello_event.set()

    def _loop(self):
        while not self._stop_event.is_set():
            try:
                data, addr = self._sock.recvfrom(4096)
            except socket.timeout:
                data = None
            except OSError:
                break

            if data is not None:
                if addr == self._server_addr or addr == self._server_alt_addr:
                    parsed = self._unpack_traversal_packet(data)
                    if parsed is not None:
                        self._handle_traversal_packet(*parsed)
                else:
                    self._handle_peer_packet(data, addr)

            now = time.monotonic()
            self._resend_traversal_packets(now)
            if self._host_code and (now - self._last_ping_time) >= self.PING_INTERVAL:
                self._send_traversal_ping()
                self._last_ping_time = now
            with self._lock:
                peers = list(self._peers_by_token.values())
            for peer in peers:
                peer.pump(now)


class CollaborationManager(QtCore.QObject):
    """
    Lightweight TCP collaboration manager for snapshot-based syncing.
    """
    DISCOVERY_TYPE = "reggie_next_collab_discover"
    DISCOVERY_REPLY_TYPE = "reggie_next_collab_here"
    PUBLIC_LOBBY_URL = "https://lobby.dolphin-emu.org"
    PUBLIC_IP_URL = "https://ip.dolphin-emu.org/"
    PUBLIC_ROOM_VERSION = "Reggie-Next-Collaboration"
    DIRECT_CONNECT_TIMEOUT_SECONDS = 8.0
    UPNP_DISCOVERY_ADDRESS = ("239.255.255.250", 1900)
    UPNP_SERVICE_TYPES = (
        "urn:schemas-upnp-org:service:WANIPConnection:1",
        "urn:schemas-upnp-org:service:WANIPConnection:2",
        "urn:schemas-upnp-org:service:WANPPPConnection:1",
    )
    UPNP_SEARCH_TARGETS = UPNP_SERVICE_TYPES + (
        "urn:schemas-upnp-org:device:InternetGatewayDevice:1",
        "upnp:rootdevice",
    )
    PUBLIC_ROOM_REGIONS = (
        ("AF", "Africa"),
        ("CN", "China"),
        ("EA", "East Asia"),
        ("EU", "Europe"),
        ("NA", "North America"),
        ("OC", "Oceania"),
        ("SA", "South America"),
    )
    statusChanged = QtCore.pyqtSignal(str)
    snapshotReceived = QtCore.pyqtSignal(bytes, int, str)
    messageReceived = QtCore.pyqtSignal(dict, str)
    peerCountChanged = QtCore.pyqtSignal(int)
    peerConnected = QtCore.pyqtSignal(str)
    participantsChanged = QtCore.pyqtSignal(object)
    banListChanged = QtCore.pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.session_id = str(uuid.uuid4())
        self.local_nickname = "Player"
        self.local_highlight_color = "#ffff00"
        self._server = None
        self._server_thread = None
        self._accept_stop = threading.Event()
        self._connections = {}
        self._conn_meta = {}
        self._connections_lock = threading.Lock()
        self._mode = None
        self._connected_addr = None
        self._send_queue = queue.Queue()
        self._send_thread = None
        self._send_stop = threading.Event()
        self._last_peer_count = 0
        self._host_port = None
        self._discovery_socket = None
        self._discovery_thread = None
        self._discovery_stop = threading.Event()
        self._participants = []
        self._ban_list = {}
        self._room_info_provider = None
        self._peer_intro_validator = None
        self._host_room_mode = "lan"
        self._public_room_secret = ""
        self._public_room_name = ""
        self._public_room_region = "EU"
        self._public_room_password = ""
        self._public_room_server_id = ""
        self._public_room_method = "direct"
        self._public_room_thread = None
        self._public_room_stop = threading.Event()
        self._upnp_control_url = ""
        self._upnp_service_type = ""
        self._upnp_internal_ip = ""
        self._upnp_external_port = 0
        self._traversal_endpoint = None
        self._debug_logger = None

    def set_debug_logger(self, logger):
        self._debug_logger = logger if callable(logger) else None

    @staticmethod
    def _debug_sanitize(value, depth=0):
        if depth >= 2:
            if isinstance(value, dict):
                return "{...}"
            if isinstance(value, (list, tuple, set)):
                return "[...]"
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if isinstance(value, bytes):
            return "<bytes:%d>" % len(value)
        if isinstance(value, dict):
            out = {}
            for key, item in list(value.items())[:12]:
                out[str(key)] = CollaborationManager._debug_sanitize(item, depth + 1)
            if len(value) > 12:
                out["..."] = "+%d keys" % (len(value) - 12)
            return out
        if isinstance(value, (list, tuple, set)):
            seq = list(value)
            out = [CollaborationManager._debug_sanitize(item, depth + 1) for item in seq[:10]]
            if len(seq) > 10:
                out.append("... +%d items" % (len(seq) - 10))
            return out
        return repr(value)

    @classmethod
    def _summarize_message_for_debug(cls, message):
        if not isinstance(message, dict):
            return cls._debug_sanitize(message)
        summary = {
            "type": str(message.get("type") or ""),
            "sender": str(message.get("sender") or ""),
        }
        if "area" in message:
            summary["area"] = cls._debug_sanitize(message.get("area"))
        payload = message.get("payload")
        if isinstance(payload, dict):
            summary["payload_keys"] = sorted(str(key) for key in payload.keys())
            for key in ("area_num", "level_name", "file_count", "total_bytes", "game_id", "host", "current_level_name", "current_area_num"):
                if key in payload:
                    summary[key] = cls._debug_sanitize(payload.get(key))
            if "download_files" in payload:
                try:
                    summary["download_files_count"] = len(payload.get("download_files") or [])
                except Exception:
                    pass
            if "files" in payload:
                try:
                    summary["files_count"] = len(payload.get("files") or [])
                except Exception:
                    pass
            if "known_files" in payload:
                try:
                    summary["known_files_count"] = len(payload.get("known_files") or {})
                except Exception:
                    pass
            if "data" in payload:
                try:
                    summary["data_len"] = len(base64.b64decode(payload.get("data") or b""))
                except Exception:
                    summary["data_len"] = "<decode-error>"
        elif payload is not None:
            summary["payload"] = cls._debug_sanitize(payload)
        elif "payload" in message:
            summary["payload"] = None
        if "payload" in message and isinstance(message.get("payload"), str):
            summary["payload_len"] = len(message.get("payload") or "")
        return summary

    def _debug(self, event, **fields):
        logger = self._debug_logger
        if logger is None:
            return
        data = {
            "event": str(event or ""),
            "mode": str(self._mode or ""),
            "session_id": str(self.session_id or ""),
        }
        for key, value in fields.items():
            data[str(key)] = self._debug_sanitize(value)
        try:
            logger(**data)
        except Exception:
            pass

    @property
    def online_count(self):
        if self._mode is None:
            return 0
        with self._connections_lock:
            return 1 + len(self._connections)

    def _emit_peer_count_if_changed(self):
        count = self.online_count
        if count != self._last_peer_count:
            self._last_peer_count = count
            self.peerCountChanged.emit(count)

    @property
    def mode(self):
        return self._mode

    def set_local_nickname(self, nickname):
        self.local_nickname = self._sanitize_nickname(nickname)
        if self._mode == "host":
            self._broadcast_roster()
        elif self._mode == "client":
            self._set_participants([self._build_local_participant()])
            self._send_identity()

    def set_local_highlight_color(self, color):
        self.local_highlight_color = self._sanitize_color(color)
        if self._mode == "host":
            self._broadcast_roster()
        elif self._mode == "client":
            self._set_participants([self._build_local_participant()])
            self._send_identity()

    def set_ban_list(self, ban_list):
        self._ban_list = self._normalize_ban_list(ban_list)
        self.banListChanged.emit(dict(self._ban_list))

    def get_ban_list(self):
        return dict(self._ban_list)

    def remove_ban(self, ip):
        ip = self._normalize_ip(ip)
        if not ip:
            return
        if ip in self._ban_list:
            self._ban_list.pop(ip, None)
            self.banListChanged.emit(dict(self._ban_list))

    def get_participants(self):
        return [dict(participant) for participant in self._participants]

    def set_room_info_provider(self, provider):
        self._room_info_provider = provider

    def set_peer_intro_validator(self, validator):
        self._peer_intro_validator = validator

    def kick_peer(self, session_id):
        if self._mode != "host":
            return False
        conn_id, meta = self._find_connection(session_id)
        if conn_id is None:
            return False
        nickname = self._sanitize_nickname(meta.get("nickname") or "Player")
        self._send_direct_message(conn_id, {
            "type": "peer_kicked",
            "sender": self.session_id,
            "payload": {
                "nickname": nickname,
            },
        })
        self.statusChanged.emit("Peer kicked: %s" % nickname)
        self._drop_connection(conn_id)
        return True

    def ban_peer(self, session_id):
        if self._mode != "host":
            return False
        conn_id, meta = self._find_connection(session_id)
        if conn_id is None:
            return False
        ip = self._normalize_ip(meta.get("ip"))
        nickname = self._sanitize_nickname(meta.get("nickname") or "Player")
        if not ip:
            return False
        self._ban_list[ip] = nickname
        self.banListChanged.emit(dict(self._ban_list))
        self._send_direct_message(conn_id, {
            "type": "peer_banned",
            "sender": self.session_id,
            "payload": {
                "ip": ip,
                "nickname": nickname,
            },
        })
        self.statusChanged.emit("Peer banned: %s (%s)" % (nickname, ip))
        self._drop_connection(conn_id)
        return True

    def start_host(self, port, room_mode="lan", public_room_config=None):
        self.stop()
        port = int(port)
        room_mode = str(room_mode or "lan").strip().lower()
        if room_mode not in {"lan", "public"}:
            room_mode = "lan"

        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("0.0.0.0", port))
        server.listen(8)
        server.settimeout(1.0)

        self._server = server
        self._host_port = port
        self._host_room_mode = room_mode
        self._accept_stop.clear()
        self._mode = "host"
        self._debug("start_host", port=port, room_mode=room_mode)
        self._ensure_sender_thread()
        if room_mode == "public":
            self.statusChanged.emit("Hosting public room on port %d" % port)
        else:
            self.statusChanged.emit("Hosting LAN room on port %d" % port)
        self._emit_peer_count_if_changed()
        self._broadcast_roster()

        self._server_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._server_thread.start()
        if room_mode == "public":
            self._start_traversal_endpoint(port, host_mode=True)
            self._publish_public_room(public_room_config or {})
        else:
            self._start_discovery_listener(port)

    def connect_to_host(self, ip, port):
        self.stop()
        requested_ip = str(ip or "").strip()
        port = int(port)
        connect_ip = requested_ip
        if connect_ip.lower() == "localhost":
            # Keep localhost joins on the IPv4 loopback that the host TCP
            # server actually listens on.
            connect_ip = "127.0.0.1"
        elif connect_ip:
            try:
                connect_ip = socket.gethostbyname(connect_ip)
            except OSError:
                connect_ip = requested_ip

        self._debug(
            "connect_to_host_begin",
            requested_ip=requested_ip,
            resolved_ip=connect_ip,
            port=port,
            timeout_seconds=self.DIRECT_CONNECT_TIMEOUT_SECONDS,
        )
        conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        conn.settimeout(float(self.DIRECT_CONNECT_TIMEOUT_SECONDS))
        connect_started = time.monotonic()
        try:
            conn.connect((connect_ip, port))
        except OSError as exc:
            self._debug(
                "connect_to_host_failed",
                requested_ip=requested_ip,
                resolved_ip=connect_ip,
                port=port,
                elapsed_ms=int((time.monotonic() - connect_started) * 1000),
                error=str(exc),
            )
            try:
                conn.close()
            except OSError:
                pass
            raise
        conn.settimeout(None)
        conn_id = self._register_connection(conn, (connect_ip, port))
        self._mode = "client"
        self._connected_addr = (connect_ip, port)
        self._ensure_sender_thread()
        self.statusChanged.emit("Connected to %s:%d" % (connect_ip, port))
        self._emit_peer_count_if_changed()
        self._set_participants([self._build_local_participant()])
        self._start_reader(conn_id, conn)
        self._send_identity(conn_id)
        self._debug(
            "connect_to_host_done",
            requested_ip=requested_ip,
            resolved_ip=connect_ip,
            port=port,
            conn_id=conn_id,
            elapsed_ms=int((time.monotonic() - connect_started) * 1000),
        )

    def connect_to_public_host(self, host_code, bind_port=None):
        self.stop()
        try_port = int(bind_port or 0)
        try:
            endpoint = _DolphinTraversalEndpoint(self, bind_port=try_port, host_mode=False)
            endpoint.start()
        except OSError:
            endpoint = _DolphinTraversalEndpoint(self, bind_port=0, host_mode=False)
            endpoint.start()
        try:
            peer = endpoint.connect_to_host_code(host_code)
        except Exception:
            endpoint.stop()
            raise
        self._traversal_endpoint = endpoint
        conn_id = self._register_connection(peer, peer.remote_addr)
        peer.assign_connection(conn_id)
        self._mode = "client"
        self._connected_addr = peer.remote_addr
        self._ensure_sender_thread()
        if peer.remote_addr:
            self.statusChanged.emit(
                "Connected via Dolphin Traversal to %s:%d" % (peer.remote_addr[0], int(peer.remote_addr[1]))
            )
        else:
            self.statusChanged.emit("Connected via Dolphin Traversal")
        self._emit_peer_count_if_changed()
        self._set_participants([self._build_local_participant()])
        self._send_identity(conn_id)

    def stop(self):
        self._debug("stop_begin")
        self._stop_public_room()
        self._stop_traversal_endpoint()
        self._mode = None
        self._connected_addr = None
        self._host_port = None
        self._host_room_mode = "lan"
        self._accept_stop.set()
        self._send_stop.set()
        self._discovery_stop.set()
        try:
            self._send_queue.put_nowait(None)
        except Exception:
            pass

        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
            self._server = None

        if self._discovery_socket is not None:
            try:
                self._discovery_socket.close()
            except OSError:
                pass
            self._discovery_socket = None

        with self._connections_lock:
            connection_items = list(self._connections.items())
            self._connections.clear()
            self._conn_meta.clear()

        for _, conn in connection_items:
            try:
                if hasattr(conn, "send_line") and hasattr(conn, "shutdown"):
                    conn.shutdown()
                else:
                    try:
                        conn.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    conn.close()
            except OSError:
                pass

        self.statusChanged.emit("Collaboration stopped")
        self._set_participants([])
        self._emit_peer_count_if_changed()
        self._debug("stop_done")

    def broadcast_snapshot(self, level_bytes, area_num):
        if not self._connections:
            return

        message = {
            "type": "snapshot",
            "sender": self.session_id,
            "area": int(area_num),
            "payload": base64.b64encode(level_bytes).decode("ascii"),
        }
        self._broadcast_message(message)

    def broadcast_message(self, message_type, payload=None):
        if not self._connections:
            return False
        if payload is None:
            payload = {}
        message = {
            "type": message_type,
            "sender": self.session_id,
            "payload": payload,
        }
        self._broadcast_message(message)
        return True

    def send_message_to(self, session_id, message_type, payload=None):
        """
        Send a message to a specific peer (host mode only).
        """
        if self._mode != "host":
            return False
        if payload is None:
            payload = {}
        conn_id, _meta = self._find_connection(session_id)
        if conn_id is None:
            return False
        message = {
            "type": message_type,
            "sender": self.session_id,
            "payload": payload,
        }
        self._send_direct_message(conn_id, message)
        return True

    def _accept_loop(self):
        while not self._accept_stop.is_set():
            try:
                conn, addr = self._server.accept()
                self._debug("accept_connection", addr=addr)
            except socket.timeout:
                continue
            except OSError:
                break

            peer_ip = self._normalize_ip(addr[0] if addr else None)
            if peer_ip in self._ban_list:
                self._send_rejection(conn, {
                    "type": "peer_banned",
                    "sender": self.session_id,
                    "payload": {
                        "ip": peer_ip,
                        "nickname": self._ban_list.get(peer_ip, "Player"),
                    },
                })
                try:
                    conn.close()
                except OSError:
                    pass
                self.statusChanged.emit("Rejected banned peer: %s" % peer_ip)
                continue

            conn_id = self._register_connection(conn, addr, emit_peer_count=False)
            self._start_reader(conn_id, conn)

    def _start_discovery_listener(self, port):
        self._discovery_stop.clear()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", int(port)))
        sock.settimeout(1.0)
        self._discovery_socket = sock
        self._discovery_thread = threading.Thread(target=self._discovery_loop, daemon=True)
        self._discovery_thread.start()

    def _discovery_loop(self):
        while not self._discovery_stop.is_set():
            try:
                raw, addr = self._discovery_socket.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break

            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                continue

            if payload.get("type") != self.DISCOVERY_TYPE:
                continue

            probe_port = int(payload.get("port", 0) or 0)
            if probe_port and self._host_port is not None and probe_port != self._host_port:
                continue

            reply = {
                "type": self.DISCOVERY_REPLY_TYPE,
                "host_name": socket.gethostname(),
                "session_id": self.session_id,
                "port": int(self._host_port or 0),
                "mode": self._mode,
                "room_mode": self._host_room_mode,
                "app": "Reggie Next",
            }
            if self._public_room_server_id:
                reply["public_server_id"] = self._public_room_server_id
            if self._public_room_method:
                reply["public_method"] = self._public_room_method
            if self._public_room_name:
                reply["public_room_name"] = self._public_room_name
            if self._public_room_region:
                reply["public_region"] = self._public_room_region
            reply.update(self._get_room_info())

            try:
                self._send_discovery_reply(self._discovery_socket, reply, addr)
            except OSError:
                continue

    def _start_reader(self, conn_id, conn):
        t = threading.Thread(target=self._reader_loop, args=(conn_id, conn), daemon=True)
        t.start()

    def _register_connection(self, conn, addr=None, emit_peer_count=True):
        if hasattr(conn, "setsockopt"):
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        conn_id = str(uuid.uuid4())
        ip = None
        port = None
        if addr:
            try:
                ip = addr[0]
            except Exception:
                ip = None
            try:
                port = int(addr[1])
            except Exception:
                port = None
        with self._connections_lock:
            self._connections[conn_id] = conn
            self._conn_meta[conn_id] = {
                "ip": self._normalize_ip(ip),
                "port": port,
                "nickname": None,
                "highlight_color": "#ffff00",
                "session_id": None,
            }
        if emit_peer_count:
            self._emit_peer_count_if_changed()
        self._debug("register_connection", conn_id=conn_id, addr=addr, emit_peer_count=emit_peer_count)
        return conn_id

    def _ensure_sender_thread(self):
        if self._send_thread is not None and self._send_thread.is_alive():
            return
        self._send_stop.clear()
        self._send_thread = threading.Thread(target=self._send_loop, daemon=True)
        self._send_thread.start()

    def _send_loop(self):
        while not self._send_stop.is_set():
            item = self._send_queue.get()
            if item is None:
                continue

            target_conn_id = None
            exclude = set()
            if isinstance(item, tuple):
                if len(item) == 3:
                    data, exclude, target_conn_id = item
                elif len(item) == 2:
                    data, exclude = item
                else:
                    continue
            else:
                continue

            if target_conn_id is not None:
                with self._connections_lock:
                    conn = self._connections.get(target_conn_id)
                if conn is None:
                    continue
                try:
                    if hasattr(conn, "send_line"):
                        conn.send_line(data)
                    else:
                        conn.sendall(data)
                except OSError:
                    self._drop_connection(target_conn_id)
                continue

            if exclude is None:
                exclude = set()

            with self._connections_lock:
                targets = list(self._connections.items())

            for conn_id, conn in targets:
                if conn_id in exclude:
                    continue
                try:
                    if hasattr(conn, "send_line"):
                        conn.send_line(data)
                    else:
                        conn.sendall(data)
                except OSError:
                    self._drop_connection(conn_id)

    def _reader_loop(self, conn_id, conn):
        f = conn.makefile("rb")
        try:
            while True:
                try:
                    raw = f.readline()
                except OSError:
                    break
                if not raw:
                    break
                raw = raw.strip()
                if not raw:
                    continue

                self._handle_received_line(conn_id, raw)

        finally:
            try:
                f.close()
            except OSError:
                pass
            self._drop_connection(conn_id)

    def _drop_connection(self, conn_id):
        conn = None
        removed_meta = None
        with self._connections_lock:
            if conn_id in self._connections:
                conn = self._connections.pop(conn_id)
            removed_meta = self._conn_meta.pop(conn_id, None)

        if conn is not None:
            try:
                if hasattr(conn, "send_line") and hasattr(conn, "shutdown"):
                    conn.shutdown()
                else:
                    conn.close()
            except OSError:
                pass
        if removed_meta is not None and self._mode == "host":
            self._broadcast_roster()
        if self._mode == "client":
            with self._connections_lock:
                has_connections = bool(self._connections)
            if not has_connections:
                self._set_participants([])
                self.statusChanged.emit("Disconnected from host")
        self._emit_peer_count_if_changed()
        self._debug("drop_connection", conn_id=conn_id, removed_meta=removed_meta)

    def _broadcast_message(self, message, exclude=None):
        if exclude is None:
            exclude = set()
        self._debug("broadcast_message", message=self._summarize_message_for_debug(message), exclude=list(exclude))
        data = (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            self._send_queue.put_nowait((data, set(exclude), None))
        except Exception:
            pass

    def _send_direct_message(self, conn_id, message):
        self._debug("send_direct_message", conn_id=conn_id, message=self._summarize_message_for_debug(message))
        data = (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            self._send_queue.put_nowait((data, None, conn_id))
        except Exception:
            pass

    def _send_rejection(self, conn, message):
        self._debug("send_rejection", message=self._summarize_message_for_debug(message))
        data = (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            conn.sendall(data)
        except OSError:
            pass

    def _find_connection(self, session_id):
        session_id = str(session_id or "")
        with self._connections_lock:
            for conn_id, meta in self._conn_meta.items():
                if conn_id == session_id or str(meta.get("session_id") or "") == session_id:
                    return conn_id, dict(meta)
        return None, {}

    def _send_identity(self, conn_id=None):
        if self._mode != "client":
            return
        payload = {
            "nickname": self.local_nickname,
            "highlight_color": self.local_highlight_color,
        }
        payload.update(self._get_room_info())
        message = {
            "type": "peer_intro",
            "sender": self.session_id,
            "payload": payload,
        }
        if conn_id is None:
            self._broadcast_message(message)
        else:
            self._send_direct_message(conn_id, message)
        self._debug("send_identity", conn_id=conn_id, nickname=self.local_nickname)

    def _set_participants(self, participants):
        cleaned = []
        for participant in participants:
            if not isinstance(participant, dict):
                continue
            cleaned.append({
                "session_id": str(participant.get("session_id") or ""),
                "nickname": self._sanitize_nickname(participant.get("nickname")),
                "highlight_color": self._sanitize_color(participant.get("highlight_color")),
                "ip": self._normalize_ip(participant.get("ip")) or "unknown",
                "is_host": bool(participant.get("is_host", False)),
            })
        self._participants = cleaned
        self.participantsChanged.emit(self.get_participants())

    def _build_local_participant(self):
        ip = "127.0.0.1"
        if self._mode == "host":
            addresses = sorted(self._get_system_ipv4_addresses())
            if addresses:
                ip = addresses[0]
        elif self._connected_addr:
            ip = self._normalize_ip(self._connected_addr[0]) or ip
        return {
            "session_id": self.session_id,
            "nickname": self.local_nickname,
            "highlight_color": self.local_highlight_color,
            "ip": ip,
            "is_host": self._mode == "host",
        }

    def _build_host_participants(self):
        participants = [self._build_local_participant()]
        with self._connections_lock:
            meta_items = list(self._conn_meta.items())
        for conn_id, meta in meta_items:
            participants.append({
                "session_id": str(meta.get("session_id") or conn_id),
                "nickname": self._sanitize_nickname(meta.get("nickname") or "Connecting..."),
                "highlight_color": self._sanitize_color(meta.get("highlight_color")),
                "ip": self._normalize_ip(meta.get("ip")) or "unknown",
                "is_host": False,
            })
        participants[1:] = sorted(participants[1:], key=lambda item: (item.get("nickname", "").lower(), item.get("ip", "")))
        return participants

    def _broadcast_roster(self):
        if self._mode != "host":
            return
        participants = self._build_host_participants()
        self._set_participants(participants)
        if not self._connections:
            return
        self._broadcast_message({
            "type": "roster",
            "sender": self.session_id,
            "payload": {
                "participants": participants,
            },
        })

    @staticmethod
    def _sanitize_nickname(nickname):
        nickname = str(nickname or "").strip()
        if not nickname:
            return "Player"
        return nickname[:32]

    @staticmethod
    def _sanitize_color(color):
        value = str(color or "").strip()
        if not value:
            return "#ffff00"
        if not value.startswith("#"):
            value = "#" + value
        if len(value) != 7:
            return "#ffff00"
        try:
            int(value[1:], 16)
        except ValueError:
            return "#ffff00"
        return value.lower()

    @staticmethod
    def _normalize_ip(ip):
        ip = str(ip or "").strip()
        return ip

    def _normalize_ban_list(self, ban_list):
        normalized = {}
        if isinstance(ban_list, dict):
            items = ban_list.items()
        else:
            items = []
        for ip, nickname in items:
            clean_ip = self._normalize_ip(ip)
            if not clean_ip:
                continue
            normalized[clean_ip] = self._sanitize_nickname(nickname)
        return normalized

    def _get_room_info(self):
        if not callable(self._room_info_provider):
            return {}
        try:
            info = self._room_info_provider()
        except Exception:
            return {}
        if not isinstance(info, dict):
            return {}
        return dict(info)

    @classmethod
    def _http_get(cls, url, timeout=8.0):
        request = urllib.request.Request(url, headers={"X-Is-Dolphin": "1"})
        with urllib.request.urlopen(request, timeout=float(timeout)) as response:
            return response.read()

    @classmethod
    def _http_get_json(cls, url, timeout=8.0):
        payload = cls._http_get(url, timeout=timeout)
        data = json.loads(payload.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Invalid response from lobby server")
        return data

    @classmethod
    def _http_get_text(cls, url, timeout=8.0):
        payload = cls._http_get(url, timeout=timeout)
        return payload.decode("utf-8", "ignore").strip()

    @classmethod
    def _http_post(cls, url, data, headers=None, timeout=8.0):
        request_headers = dict(headers or {})
        request = urllib.request.Request(url, data=data, headers=request_headers, method="POST")
        with urllib.request.urlopen(request, timeout=float(timeout)) as response:
            return response.read()

    @staticmethod
    def _xml_local_name(tag):
        if "}" in str(tag):
            return str(tag).rsplit("}", 1)[-1]
        return str(tag)

    @classmethod
    def _discover_upnp_locations(cls, timeout=1.2):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.settimeout(0.2)
        locations = set()
        try:
            for search_target in cls.UPNP_SEARCH_TARGETS:
                payload = (
                    "M-SEARCH * HTTP/1.1\r\n"
                    "HOST: 239.255.255.250:1900\r\n"
                    "MAN: \"ssdp:discover\"\r\n"
                    "MX: 2\r\n"
                    "ST: %s\r\n"
                    "\r\n"
                ) % search_target
                try:
                    sock.sendto(payload.encode("ascii", "ignore"), cls.UPNP_DISCOVERY_ADDRESS)
                except OSError:
                    continue

            deadline = time.monotonic() + float(timeout)
            while time.monotonic() < deadline:
                try:
                    raw, _addr = sock.recvfrom(8192)
                except socket.timeout:
                    continue
                except OSError:
                    break
                try:
                    response = raw.decode("utf-8", "ignore")
                except Exception:
                    continue
                for line in response.splitlines():
                    if ":" not in line:
                        continue
                    key, value = line.split(":", 1)
                    if key.strip().lower() == "location":
                        location = value.strip()
                        if location:
                            locations.add(location)
        finally:
            sock.close()
        return sorted(locations)

    @classmethod
    def _extract_upnp_service(cls, root):
        for service in root.iter():
            if cls._xml_local_name(service.tag) != "service":
                continue
            service_type = ""
            control_url = ""
            for child in list(service):
                name = cls._xml_local_name(child.tag)
                text = str(child.text or "").strip()
                if name == "serviceType":
                    service_type = text
                elif name == "controlURL":
                    control_url = text
            if service_type in cls.UPNP_SERVICE_TYPES and control_url:
                return service_type, control_url
        return None, None

    @classmethod
    def _resolve_upnp_control(cls, location):
        payload = cls._http_get(location, timeout=6.0)
        root = ET.fromstring(payload)
        base_url = ""
        url_base_node = None
        for child in list(root):
            if cls._xml_local_name(child.tag) == "URLBase":
                url_base_node = child
                break
        if url_base_node is not None:
            base_url = str(url_base_node.text or "").strip()
        if not base_url:
            base_url = location
        service_type, control_url = cls._extract_upnp_service(root)
        if not service_type or not control_url:
            raise OSError("UPnP gateway service not found")
        return service_type, urllib.parse.urljoin(base_url, control_url)

    @classmethod
    def _guess_local_ip_for_remote(cls, remote_host):
        remote_host = str(remote_host or "").strip()
        if not remote_host:
            raise OSError("UPnP gateway host is missing")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect((remote_host, 1900))
            ip = sock.getsockname()[0]
        finally:
            sock.close()
        if not cls._is_discoverable_ipv4(ip):
            raise OSError("Unable to determine LAN IP for UPnP mapping")
        return ip

    @classmethod
    def _upnp_escape(cls, value):
        text = str(value or "")
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
        )

    @classmethod
    def _upnp_soap_call(cls, control_url, service_type, action, arguments, timeout=8.0):
        body_parts = []
        for key, value in arguments:
            body_parts.append("<%s>%s</%s>" % (key, cls._upnp_escape(value), key))
        envelope = (
            "<?xml version=\"1.0\"?>"
            "<s:Envelope xmlns:s=\"http://schemas.xmlsoap.org/soap/envelope/\" "
            "s:encodingStyle=\"http://schemas.xmlsoap.org/soap/encoding/\">"
            "<s:Body>"
            "<u:%s xmlns:u=\"%s\">%s</u:%s>"
            "</s:Body>"
            "</s:Envelope>"
        ) % (action, service_type, "".join(body_parts), action)
        headers = {
            "Content-Type": "text/xml; charset=\"utf-8\"",
            "SOAPAction": '"%s#%s"' % (service_type, action),
            "Connection": "close",
        }
        try:
            return cls._http_post(control_url, envelope.encode("utf-8"), headers=headers, timeout=timeout)
        except urllib.error.HTTPError as exc:
            error_text = ""
            try:
                error_text = exc.read().decode("utf-8", "ignore").strip()
            except Exception:
                error_text = ""
            raise OSError(error_text or str(exc))

    def _ensure_upnp_port_mapping(self, port):
        port = int(port)
        locations = self._discover_upnp_locations()
        if not locations:
            self.statusChanged.emit("UPnP not available: no Internet Gateway Device found")
            return False

        last_error = ""
        for location in locations:
            try:
                service_type, control_url = self._resolve_upnp_control(location)
                gateway_host = urllib.parse.urlparse(control_url).hostname
                internal_ip = self._guess_local_ip_for_remote(gateway_host)
                try:
                    self._upnp_soap_call(
                        control_url,
                        service_type,
                        "DeletePortMapping",
                        (
                            ("NewRemoteHost", ""),
                            ("NewExternalPort", port),
                            ("NewProtocol", "TCP"),
                        ),
                        timeout=5.0,
                    )
                except Exception:
                    pass
                self._upnp_soap_call(
                    control_url,
                    service_type,
                    "AddPortMapping",
                    (
                        ("NewRemoteHost", ""),
                        ("NewExternalPort", port),
                        ("NewProtocol", "TCP"),
                        ("NewInternalPort", port),
                        ("NewInternalClient", internal_ip),
                        ("NewEnabled", 1),
                        ("NewPortMappingDescription", "Reggie Next Collaboration"),
                        ("NewLeaseDuration", 0),
                    ),
                    timeout=8.0,
                )
                self._upnp_control_url = control_url
                self._upnp_service_type = service_type
                self._upnp_internal_ip = internal_ip
                self._upnp_external_port = port
                self.statusChanged.emit("UPnP port mapping enabled: %s:%d" % (internal_ip, port))
                return True
            except Exception as exc:
                last_error = str(exc)
                continue

        if last_error:
            self.statusChanged.emit("UPnP port mapping failed: %s" % last_error)
        else:
            self.statusChanged.emit("UPnP port mapping failed")
        return False

    def _release_upnp_port_mapping(self):
        control_url = str(self._upnp_control_url or "").strip()
        service_type = str(self._upnp_service_type or "").strip()
        port = int(self._upnp_external_port or 0)
        self._upnp_control_url = ""
        self._upnp_service_type = ""
        self._upnp_internal_ip = ""
        self._upnp_external_port = 0
        if not control_url or not service_type or port <= 0:
            return
        try:
            self._upnp_soap_call(
                control_url,
                service_type,
                "DeletePortMapping",
                (
                    ("NewRemoteHost", ""),
                    ("NewExternalPort", port),
                    ("NewProtocol", "TCP"),
                ),
                timeout=5.0,
            )
        except Exception:
            pass

    @classmethod
    def _build_public_filters(cls, filters=None):
        params = {"version": cls.PUBLIC_ROOM_VERSION}
        if not isinstance(filters, dict):
            return params
        name_filter = str(filters.get("name") or "").strip()
        if name_filter:
            params["name"] = name_filter
        region_filter = str(filters.get("region") or "").strip().upper()
        if region_filter and region_filter != "ALL":
            params["region"] = region_filter
        password_filter = filters.get("password")
        if password_filter in (True, False):
            params["password"] = int(bool(password_filter))
        in_game_filter = filters.get("in_game")
        if in_game_filter in (True, False):
            params["in_game"] = int(bool(in_game_filter))
        return params

    @classmethod
    def list_public_rooms(cls, filters=None):
        params = cls._build_public_filters(filters)
        url = cls.PUBLIC_LOBBY_URL + "/v0/list?" + urllib.parse.urlencode(params)
        data = cls._http_get_json(url)
        if str(data.get("status") or "") != "OK":
            raise OSError(str(data.get("status") or "Unable to fetch public room list"))
        rooms = []
        for entry in data.get("sessions") or []:
            if not isinstance(entry, dict):
                continue
            try:
                port = int(entry.get("port", 0) or 0)
                player_count = int(entry.get("player_count", 0) or 0)
            except (TypeError, ValueError):
                continue
            server_id = str(entry.get("server_id") or "").strip()
            if not server_id or port <= 0:
                continue
            rooms.append({
                "source": "online",
                "host": "",
                "port": port,
                "host_name": str(entry.get("name") or "Public room").strip() or "Public room",
                "session_name": str(entry.get("name") or "Public room").strip() or "Public room",
                "server_id": server_id,
                "method": str(entry.get("method") or "direct").strip().lower() or "direct",
                "display_game": str(entry.get("game") or "").strip(),
                "region": str(entry.get("region") or "").strip(),
                "requires_password": bool(entry.get("password", False)),
                "player_count": player_count,
                "in_game": bool(entry.get("in_game", False)),
                "version": str(entry.get("version") or "").strip(),
            })
        return sorted(
            rooms,
            key=lambda item: (
                str(item.get("session_name") or "").lower(),
                str(item.get("region") or "").lower(),
                str(item.get("display_game") or "").lower(),
            ),
        )

    @classmethod
    def find_matching_lan_host_for_public_room(cls, room_info, resolved_host, timeout=0.35):
        if not isinstance(room_info, dict):
            return None
        try:
            port = int(room_info.get("port", 0) or 0)
        except (TypeError, ValueError):
            return None
        if port <= 0:
            return None

        resolved_host = str(resolved_host or "").strip()
        session_name = str(room_info.get("session_name") or room_info.get("host_name") or "").strip().lower()
        for candidate in cls.discover_hosts(port=port, timeout=timeout):
            candidate_public_id = str(candidate.get("public_server_id") or "").strip()
            candidate_room_name = str(candidate.get("public_room_name") or "").strip().lower()
            candidate_room_mode = str(candidate.get("room_mode") or "").strip().lower()
            if candidate_room_mode != "public":
                continue
            if resolved_host and candidate_public_id and candidate_public_id == resolved_host:
                return candidate
            if session_name and candidate_room_name and candidate_room_name == session_name:
                return candidate
        return None

    @classmethod
    def get_public_ip(cls):
        address = cls._http_get_text(cls.PUBLIC_IP_URL, timeout=6.0)
        if not cls._is_discoverable_ipv4(address):
            raise OSError("Unable to determine a public IPv4 address")
        return address

    @staticmethod
    def encrypt_public_room_id(server_id, password):
        server_id = str(server_id or "")
        password = str(password or "")
        if (not server_id) or (not password):
            return server_id
        checksum = sum(ord(ch) for ch in server_id) & 0xFF
        encoded = server_id + chr(checksum)
        output = []
        for index, ch in enumerate(encoded):
            value = (ord(ch) ^ ord(password[index % len(password)])) + index
            value &= 0xFF
            output.append(chr(ord("A") + ((value & 0xF0) >> 4)))
            output.append(chr(ord("A") + (value & 0x0F)))
        return "".join(output)

    @staticmethod
    def decrypt_public_room_id(server_id, password):
        encoded = str(server_id or "")
        password = str(password or "")
        if (not encoded) or (not password) or (len(encoded) % 2 != 0):
            return None
        decoded = []
        try:
            for index in range(0, len(encoded), 2):
                value = ((ord(encoded[index]) - ord("A")) << 4) | (ord(encoded[index + 1]) - ord("A"))
                decoded.append(value)
        except Exception:
            return None
        output = []
        for index, value in enumerate(decoded):
            value = (value - index) & 0xFF
            value ^= ord(password[index % len(password)])
            output.append(chr(value))
        if not output:
            return None
        expected_checksum = ord(output[-1])
        plain = "".join(output[:-1])
        if (sum(ord(ch) for ch in plain) & 0xFF) != expected_checksum:
            return None
        return plain

    @classmethod
    def resolve_public_room_host(cls, room_info, password=""):
        if not isinstance(room_info, dict):
            return None
        server_id = str(room_info.get("server_id") or "").strip()
        if not server_id:
            return None
        if bool(room_info.get("requires_password")):
            return cls.decrypt_public_room_id(server_id, password)
        return server_id

    def _public_room_game_label(self):
        room_info = self._get_room_info()
        game_name = str(room_info.get("game_name") or "").strip()
        game_id = str(room_info.get("game_id") or "").strip()
        return game_name or game_id or "Reggie Next"

    def _start_public_room_heartbeat(self):
        if self._public_room_thread is not None and self._public_room_thread.is_alive():
            return
        self._public_room_stop.clear()
        self._public_room_thread = threading.Thread(target=self._public_room_heartbeat_loop, daemon=True)
        self._public_room_thread.start()

    def _publish_public_room(self, config):
        config = dict(config or {})
        name = str(config.get("name") or "").strip()
        region = str(config.get("region") or "EU").strip().upper() or "EU"
        password = str(config.get("password") or "")
        if not name:
            raise ValueError("Public room name cannot be empty")
        if not password:
            raise ValueError("Public room password cannot be empty")
        traversal_endpoint = self._traversal_endpoint
        if traversal_endpoint is None:
            raise OSError("Traversal proxy is not running")
        host_code = traversal_endpoint.host_code()
        if not host_code:
            raise OSError("Traversal proxy did not receive a Dolphin host code")
        lobby_server_id = self.encrypt_public_room_id(host_code, password)
        params = {
            "name": name,
            "region": region,
            "game": self._public_room_game_label(),
            "password": 1,
            "method": "traversal",
            "server_id": lobby_server_id,
            "in_game": 0,
            "port": int(traversal_endpoint.local_port() or self._host_port or 0),
            "player_count": self.online_count,
            "version": self.PUBLIC_ROOM_VERSION,
        }
        url = self.PUBLIC_LOBBY_URL + "/v0/session/add?" + urllib.parse.urlencode(params)
        data = self._http_get_json(url)
        if str(data.get("status") or "") != "OK":
            raise OSError(str(data.get("status") or "Unable to publish public room"))
        secret = str(data.get("secret") or "").strip()
        if not secret:
            raise OSError("Lobby server did not return a session secret")
        self._public_room_secret = secret
        self._public_room_name = name
        self._public_room_region = region
        self._public_room_password = password
        self._public_room_server_id = host_code
        self._public_room_method = "traversal"
        self._start_public_room_heartbeat()
        self.statusChanged.emit("Public room published via Dolphin lobby: %s" % name)

    def _public_room_heartbeat_loop(self):
        while not self._public_room_stop.wait(5.0):
            secret = str(self._public_room_secret or "").strip()
            if not secret:
                return
            params = {
                "secret": secret,
                "player_count": self.online_count,
                "game": self._public_room_game_label(),
                "in_game": 0,
            }
            url = self.PUBLIC_LOBBY_URL + "/v0/session/active?" + urllib.parse.urlencode(params)
            try:
                data = self._http_get_json(url)
            except Exception as exc:
                self.statusChanged.emit("Public room refresh failed: %s" % str(exc))
                self._public_room_secret = ""
                return
            if str(data.get("status") or "") != "OK":
                self.statusChanged.emit("Public room refresh failed: %s" % str(data.get("status") or "UNKNOWN"))
                self._public_room_secret = ""
                return

    def _stop_public_room(self):
        self._release_upnp_port_mapping()
        self._public_room_stop.set()
        thread = self._public_room_thread
        self._public_room_thread = None
        secret = str(self._public_room_secret or "").strip()
        self._public_room_secret = ""
        self._public_room_name = ""
        self._public_room_region = "EU"
        self._public_room_password = ""
        self._public_room_server_id = ""
        self._public_room_method = "direct"
        if thread is not None and thread.is_alive():
            try:
                thread.join(timeout=0.2)
            except RuntimeError:
                pass
        if secret:
            try:
                url = self.PUBLIC_LOBBY_URL + "/v0/session/remove?" + urllib.parse.urlencode({"secret": secret})
                self._http_get(url, timeout=6.0)
            except Exception:
                pass

    def _validate_peer_intro(self, payload, meta):
        if not callable(self._peer_intro_validator):
            return None
        try:
            return self._peer_intro_validator(dict(payload or {}), dict(meta or {}))
        except Exception as exc:
            return "Unable to validate peer information: %s" % str(exc)

    @staticmethod
    def _is_discoverable_ipv4(ip):
        if not ip:
            return False
        if ip.startswith("127.") or ip.startswith("169.254."):
            return False
        return ip.count(".") == 3

    @classmethod
    def _add_discoverable_ips_from_text(cls, text, addresses):
        if not text:
            return
        for token in text.replace("(", " ").replace(")", " ").split():
            parts = token.split(".")
            if len(parts) != 4:
                continue
            try:
                if not all(0 <= int(part) <= 255 for part in parts):
                    continue
            except ValueError:
                continue
            if cls._is_discoverable_ipv4(token):
                addresses.add(token)

    @classmethod
    def _get_system_ipv4_addresses(cls):
        addresses = set()

        commands = []
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags = subprocess.CREATE_NO_WINDOW
        else:
            creationflags = 0

        if socket.gethostname():
            commands.append(["hostname", "-I"])
        if hasattr(subprocess, "STARTUPINFO"):
            startupinfo = subprocess.STARTUPINFO()
            if hasattr(subprocess, "STARTF_USESHOWWINDOW"):
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        else:
            startupinfo = None

        if hasattr(socket, "AF_INET"):
            if hasattr(subprocess, "CREATE_NO_WINDOW"):
                commands.extend((
                    ["ipconfig"],
                    ["netsh", "interface", "ipv4", "show", "addresses"],
                ))
            else:
                commands.extend((
                    ["ip", "-4", "addr"],
                    ["ifconfig"],
                ))

        for command in commands:
            try:
                output = subprocess.check_output(
                    command,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                    startupinfo=startupinfo,
                    creationflags=creationflags,
                ).decode("utf-8", "ignore")
            except (FileNotFoundError, subprocess.CalledProcessError, OSError):
                continue
            cls._add_discoverable_ips_from_text(output, addresses)

        return addresses

    @classmethod
    def get_local_ipv4_addresses(cls):
        addresses = set()

        try:
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_DGRAM):
                ip = info[4][0]
                if cls._is_discoverable_ipv4(ip):
                    addresses.add(ip)
        except OSError:
            pass

        try:
            for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
                if cls._is_discoverable_ipv4(ip):
                    addresses.add(ip)
        except OSError:
            pass

        addresses.update(cls._get_system_ipv4_addresses())

        for probe_host in ("8.8.8.8", "1.1.1.1", "192.168.0.1", "10.0.0.1"):
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.connect((probe_host, 80))
                ip = sock.getsockname()[0]
                if cls._is_discoverable_ipv4(ip):
                    addresses.add(ip)
            except OSError:
                pass
            finally:
                sock.close()

        return sorted(addresses)

    @classmethod
    def discover_hosts(cls, port=35000, timeout=0.8, stop_event=None):
        port = int(port)
        local_ips = cls.get_local_ipv4_addresses()
        candidate_hosts = []
        seen_hosts = set()

        for ip in local_ips:
            parts = ip.split(".")
            if len(parts) != 4:
                continue

            prefix = ".".join(parts[:3])
            for host in range(1, 255):
                target = "%s.%d" % (prefix, host)
                if target == ip or target in seen_hosts:
                    continue
                seen_hosts.add(target)
                candidate_hosts.append(target)

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("", 0))
        sock.settimeout(0.05)

        probe = json.dumps({
            "type": cls.DISCOVERY_TYPE,
            "port": port,
        }, separators=(",", ":")).encode("utf-8")

        try:
            for target in candidate_hosts:
                if stop_event is not None and stop_event.is_set():
                    return []
                try:
                    sock.sendto(probe, (target, port))
                except OSError:
                    continue

            deadline = time.monotonic() + float(timeout)
            found = {}

            while time.monotonic() < deadline:
                if stop_event is not None and stop_event.is_set():
                    return []

                try:
                    raw, addr = sock.recvfrom(4096)
                except socket.timeout:
                    continue
                except OSError:
                    break

                try:
                    payload = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    continue

                if payload.get("type") != cls.DISCOVERY_REPLY_TYPE:
                    continue

                host_ip = addr[0]
                host_port = int(payload.get("port", port) or port)
                key = (host_ip, host_port)
                found[key] = {
                    "host": host_ip,
                    "port": host_port,
                    "host_name": payload.get("host_name") or host_ip,
                    "session_id": payload.get("session_id", ""),
                    "app": payload.get("app", "Reggie Next"),
                    "room_mode": payload.get("room_mode", "lan"),
                    "public_server_id": payload.get("public_server_id", ""),
                    "public_room_name": payload.get("public_room_name", ""),
                    "public_region": payload.get("public_region", ""),
                    "game_id": payload.get("game_id", ""),
                    "game_name": payload.get("game_name", ""),
                    "game_plugin_hash": payload.get("game_plugin_hash", ""),
                    "game_is_custom": bool(payload.get("game_is_custom", False)),
                }

            return sorted(
                found.values(),
                key=lambda item: (item["host_name"].lower(), item["host"], item["port"]),
            )
        finally:
            sock.close()

    @classmethod
    def probe_host(cls, host, port=35000, timeout=0.8):
        host = str(host or "").strip()
        if not host:
            return None

        port = int(port)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("", 0))
        sock.settimeout(0.05)

        probe = json.dumps({
            "type": cls.DISCOVERY_TYPE,
            "port": port,
        }, separators=(",", ":")).encode("utf-8")

        try:
            try:
                sock.sendto(probe, (host, port))
            except OSError:
                return None

            deadline = time.monotonic() + float(timeout)
            while time.monotonic() < deadline:
                try:
                    raw, addr = sock.recvfrom(4096)
                except socket.timeout:
                    continue
                except OSError:
                    break

                try:
                    payload = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    continue

                if payload.get("type") != cls.DISCOVERY_REPLY_TYPE:
                    continue

                host_ip = addr[0]
                host_port = int(payload.get("port", port) or port)
                return {
                    "host": host_ip,
                    "port": host_port,
                    "host_name": payload.get("host_name") or host_ip,
                    "session_id": payload.get("session_id", ""),
                    "app": payload.get("app", "Reggie Next"),
                    "room_mode": payload.get("room_mode", "lan"),
                    "public_server_id": payload.get("public_server_id", ""),
                    "public_room_name": payload.get("public_room_name", ""),
                    "public_region": payload.get("public_region", ""),
                    "game_id": payload.get("game_id", ""),
                    "game_name": payload.get("game_name", ""),
                    "game_plugin_hash": payload.get("game_plugin_hash", ""),
                    "game_is_custom": bool(payload.get("game_is_custom", False)),
                }
        finally:
            sock.close()

        return None

    def _start_traversal_endpoint(self, port, host_mode):
        endpoint = _DolphinTraversalEndpoint(self, bind_port=port, host_mode=host_mode)
        endpoint.start()
        self._traversal_endpoint = endpoint

    def _stop_traversal_endpoint(self):
        endpoint = self._traversal_endpoint
        self._traversal_endpoint = None
        if endpoint is None:
            return
        endpoint.stop()

    def _attach_traversal_peer(self, peer, addr):
        conn_id = self._register_connection(peer, addr, emit_peer_count=False)
        peer.assign_connection(conn_id)
        self.statusChanged.emit("Traversal peer opened: %s:%d" % (addr[0], int(addr[1])))
        self._emit_peer_count_if_changed()

    def _send_discovery_reply(self, sock, reply, addr):
        sock.sendto(
            json.dumps(reply, separators=(",", ":")).encode("utf-8"),
            addr,
        )

    def _handle_discovery_packet(self, raw, addr, sock):
        if self._mode != "host":
            return False
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return False

        if payload.get("type") != self.DISCOVERY_TYPE:
            return False

        probe_port = int(payload.get("port", 0) or 0)
        if probe_port and self._host_port is not None and probe_port != self._host_port:
            return True

        reply = {
            "type": self.DISCOVERY_REPLY_TYPE,
            "host_name": socket.gethostname(),
            "session_id": self.session_id,
            "port": int(self._host_port or 0),
            "mode": self._mode,
            "room_mode": self._host_room_mode,
            "app": "Reggie Next",
        }
        if self._public_room_server_id:
            reply["public_server_id"] = self._public_room_server_id
        if self._public_room_method:
            reply["public_method"] = self._public_room_method
        if self._public_room_name:
            reply["public_room_name"] = self._public_room_name
        if self._public_room_region:
            reply["public_region"] = self._public_room_region
        reply.update(self._get_room_info())

        try:
            self._send_discovery_reply(sock, reply, addr)
        except OSError:
            return True
        return True

    def _handle_received_line(self, conn_id, raw):
        try:
            msg = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            self._debug("receive_decode_error", conn_id=conn_id, raw_preview=raw[:120])
            return

        sender = msg.get("sender", "")
        if sender == self.session_id:
            self._debug("receive_own_message_ignored", conn_id=conn_id, message=self._summarize_message_for_debug(msg))
            return
        msg_type = msg.get("type")
        self._debug("receive_message", conn_id=conn_id, message=self._summarize_message_for_debug(msg))

        if self._mode == "host" and msg_type == "peer_intro":
            payload = msg.get("payload") or {}
            meta = {}
            peer_session_id = str(sender or conn_id)
            with self._connections_lock:
                current_meta = self._conn_meta.get(conn_id)
                if current_meta is not None:
                    meta = dict(current_meta)
            rejection_message = self._validate_peer_intro(payload, meta)
            if rejection_message:
                nickname = self._sanitize_nickname(payload.get("nickname"))
                self._send_direct_message(conn_id, {
                    "type": "peer_rejected",
                    "sender": self.session_id,
                    "payload": {
                        "message": str(rejection_message),
                        "nickname": nickname,
                    },
                })
                label = nickname or meta.get("ip") or "unknown peer"
                self.statusChanged.emit("Rejected peer: %s" % label)
                self._debug("peer_intro_rejected", conn_id=conn_id, label=label, reason=rejection_message)
                self._drop_connection(conn_id)
                return
            with self._connections_lock:
                meta = self._conn_meta.get(conn_id)
                if meta is not None:
                    meta["nickname"] = self._sanitize_nickname(payload.get("nickname"))
                    meta["highlight_color"] = self._sanitize_color(payload.get("highlight_color"))
                    meta["session_id"] = peer_session_id
                    peer_ip = meta.get("ip") or "unknown"
                    peer_port = meta.get("port")
                else:
                    peer_ip = "unknown"
                    peer_port = None
            if peer_port is None:
                self.statusChanged.emit("Peer connected: %s" % peer_ip)
            else:
                self.statusChanged.emit("Peer connected: %s:%d" % (peer_ip, int(peer_port)))
            self._emit_peer_count_if_changed()
            self._broadcast_roster()
            self.peerConnected.emit(peer_session_id)
            self._debug("peer_intro_accepted", conn_id=conn_id, sender=sender, peer_ip=peer_ip, peer_port=peer_port)
            return

        if msg_type == "roster":
            payload = msg.get("payload") or {}
            self._set_participants(payload.get("participants") or [])
            return

        if self._mode == "host":
            if msg_type in {"hist_add", "hist_upd", "hist_undo", "hist_redo"}:
                relayed = dict(msg)
                relayed["sender"] = self.session_id
                pl = relayed.get("payload")
                if isinstance(pl, dict):
                    pl = dict(pl)
                    pl["origin"] = sender
                    relayed["payload"] = pl
                self._broadcast_message(relayed, exclude=set())
            else:
                self._broadcast_message(msg, exclude={conn_id})

        if msg_type == "snapshot":
            area_num = int(msg.get("area", 1))
            try:
                payload = base64.b64decode(msg.get("payload", ""))
            except (ValueError, TypeError):
                return
            self.snapshotReceived.emit(payload, area_num, sender)
        else:
            self.messageReceived.emit(msg, sender)
