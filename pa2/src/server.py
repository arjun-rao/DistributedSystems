# Code for UDP servers
import socket
import argparse
from signal import signal, SIGINT
from ftqueue import FTQueue
from logger import get_logger
import multiprocessing
from message import Message
import struct
import sys
import re

MCAST_GRP = '232.2.2.2'
MCAST_PORT = 5007
MCAST_IFACE = '192.168.1.3'
MULTICAST_TTL = 1



def ip_is_local(ip_string):
    """
    Uses a regex to determine if the input ip is on a local network. Returns a boolean.
    It's safe here, but never use a regex for IP verification if from a potentially dangerous source.
    """
    combined_regex = "(^10\.)|(^172\.1[6-9]\.)|(^172\.2[0-9]\.)|(^172\.3[0-1]\.)|(^192\.168\.)"
    return re.match(combined_regex, ip_string) is not None # is not None is just a sneaky way of converting to a boolean


def get_local_ip():
    """
    Returns the first externally facing local IP address that it can find.
    Even though it's longer, this method is preferable to calling socket.gethostbyname(socket.gethostname()) as
    socket.gethostbyname() is deprecated. This also can discover multiple available IPs with minor modification.
    We excludes 127.0.0.1 if possible, because we're looking for real interfaces, not loopback.
    Some linuxes always returns 127.0.1.1, which we don't match as a local IP when checked with ip_is_local().
    We then fall back to the uglier method of connecting to another server.
    """

    # socket.getaddrinfo returns a bunch of info, so we just get the IPs it returns with this list comprehension.
    local_ips = [ x[4][0] for x in socket.getaddrinfo('localhost', 80)
                  if ip_is_local(x[4][0]) ]

    # select the first IP, if there is one.
    local_ip = local_ips[0] if len(local_ips) > 0 else None

    # If the previous method didn't find anything, use this less desirable method that lets your OS figure out which
    # interface to use.
    if not local_ip:
        # create a standard UDP socket ( SOCK_DGRAM is UDP, SOCK_STREAM is TCP )
        temp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # Open a connection to one of Google's DNS servers. Preferably change this to a server in your control.
            temp_socket.connect(('8.8.8.8', 9))
            # Get the interface used by the socket.
            local_ip = temp_socket.getsockname()[0]
        except socket.error:
            # Only return 127.0.0.1 if nothing else has been found.
            local_ip = "127.0.0.1"
        finally:
            # Always dispose of sockets when you're done!
            temp_socket.close()
    return local_ip




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
    def __init__(self, sid, HOST, PORT, num_servers=1):
        """
        Creates a UDP server on given port and hostname

        Args:
            HOST, str: The host IP to bind the socket to.
            PORT, int: The UDP port to listen on.
        """
        self.client_socket = None
        self.multicast_socket = None
        self.HOST = HOST
        self.PORT = PORT
        self._id = sid
        self.counter = 0
        self.BUFFERSIZE = 1024
        self.GSID = 0
        # Total number of servers to find out who the responsible server is.
        self.num_servers = num_servers

        # Server's FTQueue
        self.queue = FTQueue()

        # Server's to_process queue holds messages from clients
        self.manager = multiprocessing.Manager()
        self.to_process = self.manager.list()
        self.multicast_buffer = self.manager.list()

        self._address = '{}:{}'.format(self.HOST, self.PORT)
        super(UDPServer, self).__init__(self._id, self._address)
        self._bind()

        # Capture control-C signals
        def handler(signal_received, frame):
            # Handle any cleanup here
            print('SIGINT or CTRL-C detected. Exiting gracefully')
            if self.client_socket is not None:
                self.client_socket.close()
            if self.multicast_socket is not None:
                self.multicast_socket.close()
            exit(0)
        signal(SIGINT, handler)

    def _bind(self):
        """Binds a UDP sockets to the configured hostname and port
        """
        try:
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            self.client_socket.bind((self.HOST, self.PORT))
        except Exception as e:
            self.log_exception('Failed to bind socket to host')
        # Multicast socket
        try:
            # create a UDP socket
            self.multicast_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

            # allow reuse of addresses
            self.multicast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.multicast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)

            # set multicast interface to local_ip
            self.multicast_socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(MCAST_IFACE))

            # Set multicast time-to-live to 2...should keep our multicast packets from escaping the local network
            self.multicast_socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)

            # Construct a membership request...tells router what multicast group we want to subscribe to
            membership_request = socket.inet_aton(MCAST_GRP) + socket.inet_aton(MCAST_IFACE)

            # Send add membership request to socket
            # See http://www.tldp.org/HOWTO/Multicast-HOWTO-6.html for explanation of sockopts
            self.multicast_socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership_request)
                # Bind the socket to an interface.
            # If you bind to a specific interface on the Mac, no multicast data will arrive.
            # If you try to bind to all interfaces on Windows, no multicast data will arrive.
            # Hence the following.
            if sys.platform.startswith("darwin"):
                self.multicast_socket.bind(('0.0.0.0', MCAST_PORT))
            else:
                self.multicast_socket.bind((MCAST_IFACE, MCAST_PORT))

            self.multicast_socket.sendto(str.encode('test'), (MCAST_GRP, MCAST_PORT))

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
                msg_str = msg.to_string()
                self.multicast_socket.sendto(str.encode(msg_str), (MCAST_GRP, MCAST_PORT))
                # Add to buffer
                print('MID:', msg.m_id)
                self.to_process.append(msg)

            except Exception:
                self.log_exception('An error occurred while listening for messages...')

    def handle_multicast_recv(self):
        """Reads messages from muticast port, and process:
            1)Stores in buffer
            1.1) Check if message recieved has a GSID
            If GSID: go to 2.2.1
            If no GSID:
            2) Checks if it is the responsible server by message_id % n
                2.1)If it is responsible server:
                    1. Assigns a GSID to the message
                    2. Multicasts <message_id, message, GSID>
                    3. Updates GSID
                    4. Deliver/process message
  2.2)Else:
                    1. On recieving global sequence ID:
1. Checks if GSID received matches with expected GSID:
                            If True: Updates GSID, removes message from buffer, checks  for other recieved messages to process
                            Else:
                                Check if missing GSID in toDeliver Buffer
                                If not in buffer: Adds message with GSID to toDeliver buffer,
                                    contacts responsible server for missed message
                                    On recieving missed message, go to 2.1.1
                                If in buffer: go to 2.2.1.1
        """
        self.log_info('Listening for messages...')
        while True:
            try:
                data, addr = self.multicast_socket.recvfrom(self.BUFFERSIZE)
                self.log_info('Received msg: {} from: {}'.format(data, addr))
                data = data.decode()
                msg = Message.from_string(data)
                # Step 1: Add to buffer
                print('Multicast MID:', msg.m_id)
                self.multicast_buffer.append(msg)

            except Exception:
                self.log_exception('An error occurred while listening for messages...')

    def listen(self):
        """Listens for incoming messages and handles them"""
        # Listen for client requests:
        process = multiprocessing.Process(target=self.handle_client_recv, args=())
        process.daemon = True
        process.start()
        # Check if there is a message to process:
        process_buffer = False
        multicast_flag = False
        while True:
            if self.to_process and not process_buffer:
                # There is a message in the to_process buffer.
                # Check if message ID % n + 1 == self.GSID
                print('Client Recv {}', self.to_process[0].m_id)
                to_process= True
            if self.multicast_buffer and not multicast_flag:
                # There is a message in the to_process buffer.
                # Check if message ID % n + 1 == self.GSID
                print('Multicast Recv {}', self.multicast_buffer[0].m_id)
                multicast_flag= True




if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Start a UDP server')
    parser.add_argument("--host", dest="host", default="0.0.0.0",
                        help="Host IP for server. Default is '0.0.0.0'.")
    parser.add_argument("--port", type=int, dest="port", default=8000,
                        help="Host Port for server. Default is '8000'.")
    parser.add_argument("--id", type=int, dest="id", default=1,
                        help="Server ID. Default is 1.")
    parser.add_argument("--n", type=int, dest="N", default=1,
                        help="Total number of servers. Default is 1.")
    args = parser.parse_args()
    local_ip = get_local_ip()
    print('localIp: ', local_ip)
    MCAST_IFACE = local_ip
    server = UDPServer(args.id, args.host, args.port, num_servers=args.N)
    server.listen()


    server = UDPServer(args.id, args.host, args.port, num_servers=args.N)
    server.listen()

