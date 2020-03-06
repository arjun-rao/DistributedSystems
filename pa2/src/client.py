# Code for UDP clients
import socket
import argparse

from logger import get_logger

class Client:
    def __init__(self, cid, logfile='client.log'):
        # Client address used for logging
        self._id = cid
        self.logger = get_logger(logfile=logfile, logger_name='UDPClientLogs')

    def log_info(self, msg):
        """Log at info level """
        self.logger.info('CID: {}: {}'.format(self._id, msg))

    def log_debug(self, msg):
        """Log at debug level"""
        self.logger.debug('CID: {}: {}'.format(self._id, msg))
    def log_exception(self, msg):
        """Logs an exception"""
        self.logger.exception('CID: {}: {}'.format(self._id, msg))

class UDPClient(Client):
    def __init__(self, cid):
        """
        Creates a UDP client on given port and hostname

        Args:
            HOST, str: The host IP to bind the socket to.
            PORT, int: The UDP port to listen on.
        """
        self.socket = None
        self._id = cid
        self.BUFFERSIZE = 1024
        super(UDPClient, self).__init__(self._id)
        self._bind()

    def _bind(self):
        """Binds a UDP socket to the client
        """
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        except Exception as e:
            self.log_exception('Failed to bind socket')

    def sendTo(self, HOST, PORT, msg):
        """Sends message to server"""
        self.log_info('Sending Message to {}:{}...'.format(HOST, PORT))
        try:
            message = str.encode(msg)
            self.socket.sendto(message, (HOST, PORT))
            ## Wait for reply for 2 seconds
            self.socket.settimeout(2)
            msgFromServer = self.socket.recvfrom(self.BUFFERSIZE)
            self.log_info('Received message from server: {}'.format(msgFromServer[0]))
        except socket.timeout:
            self.log_exception('Socket timed out...')
            self.socket.close()





if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Start a UDP client')
    parser.add_argument("--host", dest="host", default="0.0.0.0",
                        help="Host IP for client. Default is '0.0.0.0'.")
    parser.add_argument("--port", type=int, dest="port", default=8000,
                        help="Host Port for client. Default is '8000'.")
    args = parser.parse_args()

    client = UDPClient(1)
    host = args.host
    port = args.port
    print("Type 'help' to see possible options")
    while True:
        msg = input('> ')
        if msg == 'exit':
            break
        client.sendTo(host, port, msg)

