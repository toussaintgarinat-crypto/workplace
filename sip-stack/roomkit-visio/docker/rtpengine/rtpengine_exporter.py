#!/usr/bin/env python3
"""Prometheus exporter for RTPEngine via bencode control socket."""

import os
import socket
import struct
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

RTPENGINE_HOST = os.environ.get("RTPENGINE_HOST", "rtpengine")
RTPENGINE_PORT = int(os.environ.get("RTPENGINE_PORT", "22222"))
LISTEN_PORT = int(os.environ.get("EXPORTER_PORT", "9102"))
COOKIE = b"prom"


def bencode_decode(data):
    """Decode bencode data."""
    def decode(data, pos):
        if data[pos:pos+1] == b'd':
            result = {}
            pos += 1
            while data[pos:pos+1] != b'e':
                key, pos = decode(data, pos)
                val, pos = decode(data, pos)
                if isinstance(key, bytes):
                    key = key.decode('utf-8', errors='replace')
                result[key] = val
            return result, pos + 1
        elif data[pos:pos+1] == b'l':
            result = []
            pos += 1
            while data[pos:pos+1] != b'e':
                val, pos = decode(data, pos)
                result.append(val)
            return result, pos + 1
        elif data[pos:pos+1] == b'i':
            end = data.index(b'e', pos)
            return int(data[pos+1:end]), end + 1
        elif data[pos:pos+1].isdigit():
            colon = data.index(b':', pos)
            length = int(data[pos:colon])
            start = colon + 1
            return data[start:start+length], start + length
        else:
            raise ValueError(f"Invalid bencode at pos {pos}: {data[pos:pos+10]}")
    result, _ = decode(data, 0)
    return result


def bencode_encode(data):
    """Encode data to bencode."""
    if isinstance(data, dict):
        items = b'd'
        for k, v in data.items():
            items += bencode_encode(k) + bencode_encode(v)
        return items + b'e'
    elif isinstance(data, str):
        encoded = data.encode('utf-8')
        return str(len(encoded)).encode() + b':' + encoded
    elif isinstance(data, bytes):
        return str(len(data)).encode() + b':' + data
    elif isinstance(data, int):
        return b'i' + str(data).encode() + b'e'
    elif isinstance(data, list):
        items = b'l'
        for v in data:
            items += bencode_encode(v)
        return items + b'e'
    raise ValueError(f"Cannot bencode {type(data)}")


def query_rtpengine(command):
    """Send a command to RTPEngine and return the decoded response."""
    msg = COOKIE + b' ' + bencode_encode({"command": command})
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(2)
    try:
        sock.sendto(msg, (RTPENGINE_HOST, RTPENGINE_PORT))
        data, _ = sock.recvfrom(65535)
        # Strip cookie prefix
        space = data.index(b' ')
        return bencode_decode(data[space+1:])
    finally:
        sock.close()


def to_float(val):
    """Convert a bencode value to float."""
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, bytes):
        return float(val.decode())
    if isinstance(val, str):
        return float(val)
    return 0.0


def generate_metrics():
    """Query RTPEngine and generate Prometheus metrics."""
    try:
        stats = query_rtpengine("statistics")
    except Exception as e:
        return f"# ERROR: Failed to query RTPEngine: {e}\n"

    # Response structure: {statistics: {currentstatistics, totalstatistics, ...}, result: ok}
    inner = stats.get("statistics", stats)
    cur = inner.get("currentstatistics", {})
    total = inner.get("totalstatistics", {})
    interfaces = inner.get("interfaces", [])

    lines = []

    def gauge(name, help_text, value, labels=""):
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} gauge")
        lines.append(f"{name}{{{labels}}} {value}" if labels else f"{name} {value}")

    def counter(name, help_text, value, labels=""):
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} counter")
        lines.append(f"{name}{{{labels}}} {value}" if labels else f"{name} {value}")

    # Current sessions
    own = cur.get("sessionsown", 0)
    foreign = cur.get("sessionsforeign", 0)
    lines.append("# HELP rtpengine_sessions Owned sessions")
    lines.append("# TYPE rtpengine_sessions gauge")
    lines.append(f'rtpengine_sessions{{type="own"}} {own}')
    lines.append(f'rtpengine_sessions{{type="foreign"}} {foreign}')

    # Transcoded media
    gauge("rtpengine_transcoded_media", "Transcoded media", cur.get("transcodedmedia", 0))
    gauge("rtpengine_media_cache", "Media cache size", cur.get("mediacache", 0))
    gauge("rtpengine_player_cache", "Player cache size", cur.get("playercache", 0))

    # Media streams
    lines.append("# HELP rtpengine_mediastreams Media streams by type")
    lines.append("# TYPE rtpengine_mediastreams gauge")
    lines.append(f'rtpengine_mediastreams{{type="userspace"}} {cur.get("media_userspace", 0)}')
    lines.append(f'rtpengine_mediastreams{{type="kernel"}} {cur.get("media_kernel", 0)}')
    lines.append(f'rtpengine_mediastreams{{type="mixed"}} {cur.get("media_mixed", 0)}')

    # Packet/byte rates
    gauge("rtpengine_packetrate", "Current packet rate", cur.get("packetrate", 0))
    gauge("rtpengine_byterate", "Current byte rate", cur.get("byterate", 0))
    gauge("rtpengine_errorrate", "Current error rate", cur.get("errorrate", 0))

    # Uptime
    gauge("rtpengine_uptime_seconds", "Uptime of rtpengine", to_float(total.get("uptime", 0)))

    # Total sessions
    counter("rtpengine_sessions_total", "Total managed sessions", total.get("managedsessions", 0))

    # Closed sessions
    lines.append("# HELP rtpengine_closed_sessions_total Closed sessions by reason")
    lines.append("# TYPE rtpengine_closed_sessions_total counter")
    lines.append(f'rtpengine_closed_sessions_total{{reason="rejected"}} {total.get("rejectedsessions", 0)}')
    lines.append(f'rtpengine_closed_sessions_total{{reason="timeout"}} {total.get("timeoutsessions", 0)}')
    lines.append(f'rtpengine_closed_sessions_total{{reason="silent_timeout"}} {total.get("silenttimeoutsessions", 0)}')
    lines.append(f'rtpengine_closed_sessions_total{{reason="final_timeout"}} {total.get("finaltimeoutsessions", 0)}')
    lines.append(f'rtpengine_closed_sessions_total{{reason="offer_timeout"}} {total.get("offertimeoutsessions", 0)}')
    lines.append(f'rtpengine_closed_sessions_total{{reason="terminated"}} {total.get("regularterminatedsessions", 0)}')
    lines.append(f'rtpengine_closed_sessions_total{{reason="force_terminated"}} {total.get("forcedterminatedsessions", 0)}')

    # Relayed packets/bytes
    lines.append("# HELP rtpengine_packets_total Total relayed packets")
    lines.append("# TYPE rtpengine_packets_total counter")
    lines.append(f'rtpengine_packets_total{{type="userspace"}} {total.get("relayedpackets_user", 0)}')
    lines.append(f'rtpengine_packets_total{{type="kernel"}} {total.get("relayedpackets_kernel", 0)}')

    lines.append("# HELP rtpengine_packet_errors_total Total relayed packet errors")
    lines.append("# TYPE rtpengine_packet_errors_total counter")
    lines.append(f'rtpengine_packet_errors_total{{type="userspace"}} {total.get("relayedpacketerrors_user", 0)}')
    lines.append(f'rtpengine_packet_errors_total{{type="kernel"}} {total.get("relayedpacketerrors_kernel", 0)}')

    lines.append("# HELP rtpengine_bytes_total Total relayed bytes")
    lines.append("# TYPE rtpengine_bytes_total counter")
    lines.append(f'rtpengine_bytes_total{{type="userspace"}} {total.get("relayedbytes_user", 0)}')
    lines.append(f'rtpengine_bytes_total{{type="kernel"}} {total.get("relayedbytes_kernel", 0)}')

    # Stream quality counters
    counter("rtpengine_zero_packet_streams_total", "Streams with no relayed packets", total.get("zerowaystreams", 0))
    counter("rtpengine_one_way_sessions_total", "One-way streams", total.get("onewaystreams", 0))

    # Call duration
    gauge("rtpengine_call_duration_avg", "Average call duration", to_float(total.get("avgcallduration", 0)))
    counter("rtpengine_call_duration_total", "Total calls duration", to_float(total.get("totalcallsduration", 0)))

    # MOS
    mos = inner.get("mos", {})
    counter("rtpengine_mos_total", "Sum of all MOS values", to_float(mos.get("mos_total", 0)))
    counter("rtpengine_mos_samples_total", "Total MOS samples", mos.get("mos_samples_total", 0))

    # VoIP metrics
    voip = inner.get("voip_metrics", {})
    counter("rtpengine_jitter_total", "Sum of jitter values", to_float(voip.get("jitter_total", 0)))
    counter("rtpengine_jitter_samples_total", "Total jitter samples", voip.get("jitter_samples_total", 0))
    counter("rtpengine_rtt_e2e_total", "Sum of e2e RTT values", to_float(voip.get("rtt_e2e_total", 0)))
    counter("rtpengine_rtt_e2e_samples_total", "Total e2e RTT samples", voip.get("rtt_e2e_samples_total", 0))
    counter("rtpengine_packetloss_total", "Sum of packet loss values", to_float(voip.get("packetloss_total", 0)))
    counter("rtpengine_packetloss_samples_total", "Total packet loss samples", voip.get("packetloss_samples_total", 0))

    # Packet loss/duplicates (gauges from current stats)
    gauge("rtpengine_packets_lost", "Packets lost", total.get("packets_lost", voip.get("packets_lost", 0)))
    gauge("rtpengine_rtp_duplicates", "Duplicate RTP packets", total.get("rtp_duplicates", voip.get("duplicates", 0)))
    gauge("rtpengine_rtp_skips", "RTP sequence skips", total.get("rtp_skips", voip.get("rtp_skips", 0)))
    gauge("rtpengine_rtp_seq_resets", "RTP sequence resets", total.get("rtp_seq_resets", voip.get("rtp_seq_resets", 0)))
    gauge("rtpengine_rtp_reordered", "Out-of-order RTP packets", total.get("rtp_reordered", voip.get("rtp_reordered", 0)))

    # Control statistics (offer/answer/delete counts)
    ctrl = inner.get("controlstatistics", {})
    counter("rtpengine_offer_total", "Total offer commands", ctrl.get("totaloffercount", 0))
    counter("rtpengine_answer_total", "Total answer commands", ctrl.get("totalanswercount", 0))
    counter("rtpengine_delete_total", "Total delete commands", ctrl.get("totaldeletecount", 0))

    # Interface port usage
    for iface in interfaces:
        name = iface.get("name", b"unknown")
        if isinstance(name, bytes):
            name = name.decode()
        ports = iface.get("ports", {})
        lines.append("# HELP rtpengine_ports_used RTP ports in use")
        lines.append("# TYPE rtpengine_ports_used gauge")
        lines.append(f'rtpengine_ports_used{{interface="{name}"}} {ports.get("used", 0)}')
        lines.append("# HELP rtpengine_ports_total Total available RTP ports")
        lines.append("# TYPE rtpengine_ports_total gauge")
        lines.append(f'rtpengine_ports_total{{interface="{name}"}} {ports.get("totals", 0)}')

    return "\n".join(lines) + "\n"


class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/metrics":
            metrics = generate_metrics()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.end_headers()
            self.wfile.write(metrics.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress request logging


if __name__ == "__main__":
    print(f"RTPEngine exporter listening on :{LISTEN_PORT}, querying {RTPENGINE_HOST}:{RTPENGINE_PORT}")
    server = HTTPServer(("0.0.0.0", LISTEN_PORT), MetricsHandler)
    server.serve_forever()
