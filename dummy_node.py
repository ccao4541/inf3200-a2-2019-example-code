#!/usr/bin/env python
import argparse
import json
import re
import signal
import socket
import threading

# Logger
import logging
logging.basicConfig()
logger = logging.getLogger()

# Python version check
import sys

if sys.version_info[0] <= 2:
    import httplib
    import urlparse
    from BaseHTTPServer import BaseHTTPRequestHandler,HTTPServer

elif sys.version_info[0] >= 3:
    import http.client as httplib
    from http.server import BaseHTTPRequestHandler,HTTPServer

else:
    logger.warn("Unexpected Python version", sys.version_info())

# Assignment 1 node properties
object_store = {}
neighbours = []

# Assignment 2 node properties
node_name = None
node_key = None
successor = None
other_neighbors = []
sim_crash = False

class NodeHttpHandler(BaseHTTPRequestHandler):

    def send_whole_response(self, code, content, content_type="text/plain"):
        self.send_response(code)
        self.send_header('Content-type', content_type)
        self.send_header('Content-length',len(content))
        self.end_headers()
        if sys.version_info[0] >= 3 and isinstance(content, str):
            content = content.encode()
        self.wfile.write(content)

    def extract_key_from_path(self, path):
        return re.sub(r'/storage/?(\w+)', r'\1', path)


    def do_PUT(self):
        if sys.version_info[0] <= 2:
            content_length = int(self.headers.getheader('content-length', 0))
        else:
            content_length = int(self.headers.get('content-length', 0))

        key = self.extract_key_from_path(self.path)
        value = self.rfile.read(content_length)

        object_store[key] = value

        # Send OK response
        self.send_whole_response(200, "Value stored for " + key)


    def do_GET(self):
        if self.path == "/node-info":
            node_info = {
                    "node_key": node_key,
                    "successor": successor,
                    "others": other_neighbors,
                    "sim_crash": sim_crash,
                    }
            node_info_json = json.dumps(node_info, indent=2)
            self.send_whole_response(200, node_info_json, content_type="application/json")

        elif sim_crash == True:
            self.send_whole_response(500, "I have sim-crashed")

        elif self.path.startswith("/storage/"):
            key = self.extract_key_from_path(self.path)

            if key in object_store:
                self.send_whole_response(200, object_store[key])
            else:
                self.send_whole_response(404,
                        "No object with key '%s' on this node" % key)

        elif self.path in ["/neighbours", "/neighbors"]:
            self.send_whole_response(200, "\n".join(neighbours) + "\n")

        else:
            self.send_whole_response(404, "Unknown path: " + self.path)

    def do_POST(self):
        global successor
        global sim_crash

        if self.path == "/sim-recover":
            sim_crash = False
            self.send_whole_response(200, "")

        elif self.path == "/sim-crash":
            sim_crash = True
            self.send_whole_response(200, "")

        elif sim_crash == True:
            self.send_whole_response(500, "I have sim-crashed")

        elif self.path == "/leave":
            successor = node_name
            self.send_whole_response(200, "")

        elif self.path.startswith("/join"):
            nprime = re.sub(r'^/join\?nprime=([\w:-]+)$', r'\1', self.path)
            successor = nprime
            self.send_whole_response(200, "")

        else:
            self.send_whole_response(404, "Unknown path: " + self.path)

def parse_args():
    PORT_DEFAULT = 8000
    DIE_AFTER_SECONDS_DEFAULT = 20 * 60
    parser = argparse.ArgumentParser(prog="node", description="DHT Node")

    parser.add_argument("-p", "--port", type=int, default=PORT_DEFAULT,
            help="port number to listen on, default %d" % PORT_DEFAULT)

    parser.add_argument("--die-after-seconds", type=float,
            default=DIE_AFTER_SECONDS_DEFAULT,
            help="kill server after so many seconds have elapsed, " +
                "in case we forget or fail to kill it, " +
                "default %d (%d minutes)" % (DIE_AFTER_SECONDS_DEFAULT, DIE_AFTER_SECONDS_DEFAULT/60))

    parser.add_argument("neighbours", type=str, nargs="*",
            help="addresses (host:port) of neighbour nodes")

    return parser.parse_args()


if __name__ == "__main__":

    args = parse_args()

    server = HTTPServer(('', args.port), NodeHttpHandler)
    node_name = "{}:{}".format(socket.gethostname(), args.port)
    node_key = hash(node_name)

    logger = logging.getLogger(node_name)
    logger.setLevel(logging.INFO)

    if len(args.neighbours) == 0:
        successor = node_name

    if len(args.neighbours) >= 1:
        successor = args.neighbours[0]
        other_neighbors = args.neighbours[1:]

    neighbours = args.neighbours

    def run_server():
        logger.info("Starting server on port %d" , args.port)
        server.serve_forever()
        logger.info("Server has shut down")

    def shutdown_server_on_signal(signum, frame):
        logger.info("We get signal (%s). Asking server to shut down", signum)
        server.shutdown()

    # Start server in a new thread, because server HTTPServer.serve_forever()
    # and HTTPServer.shutdown() must be called from separate threads
    thread = threading.Thread(target=run_server)
    thread.daemon = True
    thread.start()

    # Shut down on kill (SIGTERM) and Ctrl-C (SIGINT)
    signal.signal(signal.SIGTERM, shutdown_server_on_signal)
    signal.signal(signal.SIGINT, shutdown_server_on_signal)

    # Wait on server thread, until timeout has elapsed
    #
    # Note: The timeout parameter here is also important for catching OS
    # signals, so do not remove it.
    #
    # Having a timeout to check for keeps the waiting thread active enough to
    # check for signals too. Without it, the waiting thread will block so
    # completely that it won't respond to Ctrl-C or SIGTERM. You'll only be
    # able to kill it with kill -9.
    thread.join(args.die_after_seconds)
    if thread.isAlive():
        logger.info("Reached %.3f second timeout. Asking server to shut down", args.die_after_seconds)
        server.shutdown()

    logger.info("Exited cleanly")
