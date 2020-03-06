# Code for UDP servers
import socket
import argparse
from signal import signal, SIGINT

from logger import get_logger

class Server:
    def __init__(self, sid, address, logfile='server.log'):
        # Server address used for logging
        self._address = address
        self._id = sid
        self.logger = get_logger(logfile=logfile, logger_name='UDPServerLogs')

    def log_info(self, msg):
        """Log at info level """
        self.logger.info('SID: {} ({}): {}'.format(self._id, self._address, msg))

    def log_debug(self, msg):
        """Log at debug level"""
        self.logger.debug('SID: {} ({}): {}'.format(self._id, self._address, msg))
    def log_exception(self, msg):
        """Logs an exception"""
        self.logger.exception('SID: {} ({}): {}'.format(self._id, self._address, msg))

class UDPServer(Server):
    def __init__(self, sid, HOST, PORT):
        """
        Creates a UDP server on given port and hostname

        Args:
            HOST, str: The host IP to bind the socket to.
            PORT, int: The UDP port to listen on.
        """
        self.socket = None
        self.HOST = HOST
        self.PORT = PORT
        self._id = sid
        self.BUFFERSIZE = 1024

        self._address = '{}:{}'.format(self.HOST, self.PORT)
        super(UDPServer, self).__init__(self._id, self._address)
        self._bind()
        def handler(signal_received, frame):
            # Handle any cleanup here
            print('SIGINT or CTRL-C detected. Exiting gracefully')
            if self.socket is not None:
                self.socket.close()
            exit(0)
        signal(SIGINT, handler)

    def _bind(self):
        """Binds a UDP socket to the configured hostname and port
        """
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.bind((self.HOST, self.PORT))
        except Exception as e:
            self.log_exception('Failed to bind socket to host')

    def listen(self):
        """Listens for incoming messages and handles them"""
        self.log_info('Listening...')
        while True:
            try:
                data, addr = self.socket.recvfrom(self.BUFFERSIZE)
                print ("Message: ", data)
                # Send reply to client
                self.socket.sendto(data, addr)
            except Exception:
                self.log_exception('An error occurred while listening for messages...')




if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Start a UDP server')
    parser.add_argument("--host", dest="host", default="0.0.0.0",
                        help="Host IP for server. Default is '0.0.0.0'.")
    parser.add_argument("--port", type=int, dest="port", default=8000,
                        help="Host Port for server. Default is '8000'.")
    args = parser.parse_args()

    server = UDPServer(0, args.host, args.port)
    server.listen()

