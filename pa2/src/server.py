# Code for UDP servers
import socket
import argparse
from signal import signal, SIGINT
from ftqueue import FTQueue
from logger import get_logger
import multiprocessing
from message import Message

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
        self.client_socket = None
        self.HOST = HOST
        self.PORT = PORT
        self._id = sid
        self.counter = 0
        self.BUFFERSIZE = 1024

        # Server's FTQueue
        self.queue = FTQueue()
        self.manager = multiprocessing.Manager()
        # Server's to_process queue holds messages from clients
        self.to_process = self.manager.list()

        self._address = '{}:{}'.format(self.HOST, self.PORT)
        super(UDPServer, self).__init__(self._id, self._address)
        self._bind()
        def handler(signal_received, frame):
            # Handle any cleanup here
            print('SIGINT or CTRL-C detected. Exiting gracefully')
            if self.client_socket is not None:
                self.client_socket.close()
            exit(0)
        signal(SIGINT, handler)

    def _bind(self):
        """Binds a UDP socket to the configured hostname and port
        """
        try:
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            self.client_socket.bind((self.HOST, self.PORT))
        except Exception as e:
            self.log_exception('Failed to bind socket to host')

    def process_message(self, message):
        """Process incoming messages from client and perform queue operations
        """
        # messages are of the following syntax:
        # 'command_type-arg1-arg2'
        message_parts = message.split('_')
        command_type = message_parts[0]
        # command_args looks like ['arg1', 'arg2'...]
        command_args = message_parts[1:]
        if command_type == "create":
            qid = self.queue.qCreate(int(command_args[0]))
            return self.make_response(command_type,qid)
        elif command_type == "delete":
            qid = self.queue.qDestroy(int(command_args[0]))
            return self.make_response(command_type,qid)
        elif command_type == "push":
            self.queue.qPush(int(command_args[0]),int(command_args[1]))
            return self.make_response(command_type,int(command_args[0]),int(command_args[1]))
        elif command_type == "pop":
            item = self.queue.qPop(int(command_args[0]))
            print('I am here!!!')
            return self.make_response(command_type, item)
        elif command_type == "top":
            item = self.queue.qTop(int(command_args[0]))
            return self.make_response(command_type, item)
        elif command_type == "size":
            item = self.queue.qSize(int(command_args[0]))
            return self.make_response(command_type,item)

        #TODO: handle error codes from queue

    def make_response(self, command_type, *args):
        args = list(map(str, args))
        args.insert(0, command_type)
        return '_'.join(args)

    def handle_client_recv(self):
        """Reads messages from client, and process:
            1) Assign message ID - f'{SID}0{self.counter}'
            2) Multicast message
            3) Move to to_process buffer
        """
        self.log_info('Started Deamon Process')
        while True:
            try:
                data, addr = self.client_socket.recvfrom(self.BUFFERSIZE)
                self.log_info('Received msg: {} from: {}'.format(data, addr))
                data = data.decode()
                # Increment local message counter
                self.counter += 1
                # Assign Message ID
                mid = int(f'{self._id}0{self.counter}')
                msg = Message(mid, data, addr)
                # Multicast
                # TODO: Multicast here
                # Add to buffer
                print('MID:', msg.m_id)
                self.to_process.append(msg)

            except Exception:
                self.log_exception('An error occurred while listening for messages...')

    def listen(self):
        """Listens for incoming messages and handles them"""
        # Listen for client requests:
        process = multiprocessing.Process(target=self.handle_client_recv, args=())
        process.daemon = True
        process.start()
        # Check if there is a message to process:
        while True:
            if self.to_process:
                # There is a message in the to_process buffer.
                pass




if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Start a UDP server')
    parser.add_argument("--host", dest="host", default="0.0.0.0",
                        help="Host IP for server. Default is '0.0.0.0'.")
    parser.add_argument("--port", type=int, dest="port", default=8000,
                        help="Host Port for server. Default is '8000'.")
    parser.add_argument("--id", type=int, dest="id", default=1,
                        help="Server ID. Default is 1.")
    args = parser.parse_args()

    server = UDPServer(args.id, args.host, args.port)
    server.listen()

