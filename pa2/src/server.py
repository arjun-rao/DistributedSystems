# Code for UDP servers
import socket
import argparse
from signal import signal, SIGINT
from ftqueue import FTQueue, QueueErrors
from logger import get_logger
import multiprocessing
from multiprocessing import SimpleQueue
from message import Message, MessageType
import struct
import sys
import re
import time

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

class BaseServer:
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
    def log_error(self, msg):
        """Log at debug level"""
        self.logger.error('SID: {} ({}): {}'.format(self._id, self._address, msg))
    def log_exception(self, msg):
        """Logs an exception"""
        self.logger.exception('SID: {} ({}): {}'.format(self._id, self._address, msg))

class UDPServer(BaseServer):
    def __init__(self, sid, HOST, PORT, num_servers=1):
        """
        Creates a UDP server on given port and hostname

        Args:
            HOST, str: The host IP to bind the socket to.
            PORT, int: The UDP port to listen on.
        """
        self.unicast_socket = None
        self.multicast_socket = None
        self.HOST = HOST
        self.PORT = PORT
        self._id = sid
        self.BUFFERSIZE = 1024
        # Total number of servers to find out who the responsible server is.
        self.num_servers = num_servers

        self.manager = multiprocessing.Manager()

        # Server's FTQueue
        self.queue = FTQueue(self.manager)

        self.GSID = multiprocessing.Value('i', 0)
        self.maxGSID = multiprocessing.Value('i', 0)
        self.counter = multiprocessing.Value('i', 0)
        # Server's from_client buffer holds messages from clients as a dict
        # to send reply to client later.
        self.from_client = self.manager.dict()
        # Any message received via multicast from other servers
        self.multicast_buffer = SimpleQueue()
        # raw_message_buffer stores any messages that are received without sequence number.
        self.raw_message_buffer = self.manager.list()
        # Messages that this server is responsible for
        self.delivered_messages = self.manager.dict()

        # Messages that have GSID > self.GSID
        self.to_deliver = self.manager.dict()

        self._address = '{}:{}'.format(self.HOST, self.PORT)
        super(UDPServer, self).__init__(self._id, self._address)
        self._bind()

        # Capture control-C signals
        def sigint_handler(signal_received, frame):
            # Handle any cleanup here
            print('SIGINT or CTRL-C detected. Exiting gracefully')
            if self.unicast_socket is not None:
                self.unicast_socket.close()
            if self.multicast_socket is not None:
                self.multicast_socket.close()
            exit(0)
        signal(SIGINT, sigint_handler)

    def _bind(self):
        """Binds a UDP sockets to the configured hostname and port
        """
        try:
            self.unicast_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            self.unicast_socket.bind((self.HOST, self.PORT))
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
        try:
            if command_type == "create":
                qid, err = self.queue.qCreate(int(command_args[0]))
                return self.make_response(command_type,qid, err)
            elif command_type == "delete":
                qid, err = self.queue.qDestroy(int(command_args[0]))
                return self.make_response(command_type,qid, err)
            elif command_type == "push":
                _, err = self.queue.qPush(int(command_args[0]),int(command_args[1]))
                return self.make_response(command_type,int(command_args[0]),int(command_args[1]), err)
            elif command_type == "pop":
                item, err = self.queue.qPop(int(command_args[0]))
                return self.make_response(command_type, item, err)
            elif command_type == "top":
                item, err = self.queue.qTop(int(command_args[0]))
                return self.make_response(command_type, item, err)
            elif command_type == "size":
                item, err = self.queue.qSize(int(command_args[0]))
                return self.make_response(command_type,item, err)
        except Exception:
                self.log_exception('Unknown Error')
                return self.make_response(command_type, QueueErrors.UNKNOWN)
        return self.make_response(command_type, QueueErrors.UNKNOWN)

    def deliver_message(self, message):
        """Process this message and send a reply to the client"""
        if self.GSID.value != message.gs_id:
            self.log_error('Cannot deliver this message at this time')
            return

        # Process the message
        response_data, response_err = self.process_message(message.data)

        self.log_info('Delivered Message: {}'.format(message.m_id))

        # Print the queue to console for debugging
        self.queue.qDisplay()

        # Update GSID
        with self.GSID.get_lock():
            self.GSID.value += 1

        with self.maxGSID.get_lock():
            self.maxGSID.value = max(self.maxGSID.value, self.GSID.value)

        # remove message from raw_message_buffer
        for idx, raw_msg in enumerate(self.raw_message_buffer):
            if raw_msg.m_id == message.m_id:
                self.raw_message_buffer.pop(idx)
                self.log_debug('Removed msg({}) from raw_message_buffer'.format(raw_msg.m_id))
                break

        # Check if we need to send a reply to the client
        if message.m_id in self.from_client:
            original_client_message = self.from_client[message.m_id]
            client_address = original_client_message.sender
            # change data to response
            message.data = response_data
            if response_err is not None:
                message.error = response_err
            # send reply to client
            self.unicast_message(message, client_address, MessageType.SERVER_CLIENT_REPLY)
            # Remove client message from buffer
            del self.from_client[message.m_id]

        # Check if any other messages can be delivered
        if self.GSID.value in self.to_deliver:
            new_message = self.to_deliver[self.GSID.value]
            del self.to_deliver[self.GSID.value]
            self.deliver_message(new_message)

    def is_responsible_server(self, msg):
        """Returns true if this server is responsible for msg"""
        if ((msg.m_id % self.num_servers) + 1) == self._id:
            return True
        return False

    def get_responsible_server(self, msg):
        """Returns the ID of the responsible server for this message"""
        return ((msg.m_id % self.num_servers) + 1)

    def make_response(self, command_type, *args):
        params = list(map(str, args))
        err = params[-1]
        params.insert(0, command_type)
        response = '_'.join(params[:-1])
        if err != 'None':
            self.log_error('Delivery error: {} ({})'.format(response, str(err)))
            return response, str(err)
        self.log_info('Delivery success: {}'.format(response))
        return  response, None

    def handle_client_message(self, msg, sender_address):
        """Handle messages received by clients"""
        self.log_info('Client Received msg: {} from: {}'.format(msg.m_id, sender_address))
        # Increment local message
        with self.counter.get_lock():
            self.counter.value += 1
        # Assign Message ID and sender address
        msg.m_id = int(f'{self._id}0{self.counter.value}')
        msg.sender = sender_address
        # Add message to from_client buffer
        self.from_client[msg.m_id] = msg
        # Multicast the message to all servers
        print('Sending multicast MID:', msg.m_id)
        self.multicast_message(msg, MessageType.MULTICAST_RAW)
        # Check if self is responsible for this message
        if self.is_responsible_server(msg):
            # Issue global sequence number and multicast it
            self.handle_raw_multicast_message(msg)

    def request_retransmit_messages(self):
        # TODO: Request for retransmission or deliver any that can be in to_deliver

        self.log_debug('Missing messages from GSID: {} - {}'.format(self.GSID.value, self.maxGSID.value))

    def handle_raw_multicast_message(self, msg: Message):
        """Checks if self is responsible, otherwise stores in raw_message buffer
        """
        if self.is_responsible_server(msg):
            # Check if missing any messages:
            if self.maxGSID.value != self.GSID.value:
                # Check for possible duplicates and store message in raw_message buffer
                if not any(x for x in self.raw_message_buffer if x.m_id == msg.m_id):
                    # self.log_info('Storing message: {} for future use.'.format(msg.m_id))
                    self.raw_message_buffer.append(msg)
                self.request_retransmit_messages()
            else:
                # Issue the global sequence number to this message and multicast
                msg.gs_id = self.GSID.value
                self.log_info('GSID {} Issued to message: {}'.format(self.GSID.value, msg.m_id))
                self.multicast_message(msg, MessageType.MULTICAST_SEQUENCED)
                # Deliver the message locally.
                self.deliver_message(msg)
        else:
            # Check for possible duplicates and store message in raw_message buffer
            if not any(x for x in self.raw_message_buffer if x.m_id == msg.m_id):
                self.log_info('Storing message: {} for future use.'.format(msg.m_id))
                self.raw_message_buffer.append(msg)

    def handle_sequenced_multicast_message(self, msg):
        # if expected GSID and message GSID match, deliver message
        if msg.gs_id == self.GSID.value:
            # Deliver the message and update GSID
            self.deliver_message(msg)
        elif msg.gs_id > self.GSID.value:
            # Add message to to_deliver buffer
            self.to_deliver[msg.gs_id] = msg
            with self.maxGSID.get_lock():
                self.maxGSID.value = max(self.maxGSID.value, msg.gs_id)
            self.request_retransmit_messages()

    def handle_unicast_recv(self):
        """Reads messages from client, and process:
            1) Assign message ID - f'{SID}0{self.counter}'
            2) Multicast message
            3) Move to from_client buffer
        """
        self.log_info('Started Deamon Process')
        while True:
            try:
                data, addr = self.unicast_socket.recvfrom(self.BUFFERSIZE)
                data = data.decode()
                msg = Message.from_string(data)
                if msg.message_type == MessageType.CLIENT_REQUEST:
                    self.handle_client_message(msg, addr)
                # TODO: Handle nack response

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
                    1. On receiving global sequence ID:
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
                data = data.decode()
                try:
                    msg = Message.from_string(data)
                    # Step 1: Add to buffer
                    if msg.sender_type == "server" and msg.sender_id != self._id:
                        self.log_info('Received Multicast MID: {} from: {}({})'.format(msg.m_id, msg.sender_type, msg.sender_id))
                        self.multicast_buffer.put(msg)
                except:
                    self.log_debug('Failed to decode multicast message: {}'.format(data))

            except Exception:
                self.log_exception('An error occurred while listening for messages...')

    def unicast_message(self, msg, dest, msg_type):
        """Send a unicast message to provided destination
        """
        try:
            unicast_msg = Message(
                msg.m_id, msg.data,
                sender=[self.HOST, self.PORT],
                gsid=msg.gs_id,
                sender_id=self._id,
                sender_type='server',
                message_type=msg_type,
                error= msg.error
            )
            msg_str = unicast_msg.to_string()
            self.unicast_socket.sendto(str.encode(msg_str), dest)
        except:
            self.log_exception('Failed to send unicast message: {}'.format(msg_str))


    def multicast_message(self, msg, msg_type):
        """Send a multicast message
        """
        try:
            multicast_msg = Message(
                msg.m_id, msg.data,
                sender=[self.HOST, self.PORT],
                gsid=msg.gs_id,
                sender_id=self._id,
                sender_type='server',
                message_type=msg_type,
                error=msg.error
            )
            msg_str = multicast_msg.to_string()
            self.multicast_socket.sendto(str.encode(msg_str), (MCAST_GRP, MCAST_PORT))
        except:
            self.log_exception('Failed to multicast message: {}'.format(msg_str))

    def listen(self):
        """Listens for incoming messages and handles them"""
        # Listen for unicast requests:
        unicast_process = multiprocessing.Process(target=self.handle_unicast_recv, args=())
        unicast_process.daemon = True
        unicast_process.start()

        # Listen for multicast requests:
        multicast_process = multiprocessing.Process(target=self.handle_multicast_recv, args=())
        multicast_process.daemon = True
        multicast_process.start()

        while True:
            if not self.multicast_buffer.empty():
                # There is a message in the multicast buffer.
                msg = self.multicast_buffer.get()
                # If receving a sequenced multicast message
                if msg.has_gsid() and msg.message_type == MessageType.MULTICAST_SEQUENCED:
                    self.log_debug('Processing sequenced multicast msg: self.gsid: {}, msg.ID:{}, msg.GSID: {}'.format(self.GSID.value, msg.m_id, msg.gs_id))
                    # Check if we can deliver or buffer it
                    self.handle_sequenced_multicast_message(msg)
                elif msg.message_type == MessageType.MULTICAST_RAW:
                    self.log_debug('Processing raw multicast msg: self.gsid: {}, msg.ID:{}, msg.GSID: {}'.format(self.GSID.value, msg.m_id, msg.gs_id))
                    # Check if self is responsible if so, issue GSID and multicast
                    # Otherwise, store message in raw_message buffer
                    self.handle_raw_multicast_message(msg)
            if len(self.raw_message_buffer) > 0:
                self.handle_raw_multicast_message(self.raw_message_buffer.pop(0))
            time.sleep(1)

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

