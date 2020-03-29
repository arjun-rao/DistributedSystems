# Code for UDP servers
import socket
import argparse
import struct
import sys
import re
import time
from signal import signal, SIGINT
from ftqueue import FTQueue, QueueErrors
from logger import get_logger
import multiprocessing
from multiprocessing import SimpleQueue

from message import Message, MessageType
from config import Config, ConfigStage


MCAST_GRP = '224.1.1.1'
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
    def __init__(self, sid, HOST, PORT):
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
        self.manager = multiprocessing.Manager()
        self.config = Config(self.manager, self._id)

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
        # Any message received from clients that have not been processed.
        self.raw_client_buffer = SimpleQueue()
        # raw_message_buffer stores any messages that are received without sequence number.
        self.raw_message_buffer = self.manager.list()
        # Messages that this server is responsible for
        self.delivered_messages = self.manager.dict()
        #Cofig Messages recieved, includes config ACKS
        self.config_msg_buffer = SimpleQueue()

        # determines whether to process or halt messages in other buffers
        self.config_mode = multiprocessing.Value('i', ConfigStage.STABLE)

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
            if sys.platform.startswith('darwin'):
                self.multicast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.multicast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)

            # # set multicast interface to local_ip
            # self.multicast_socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(MCAST_IFACE))

            # # Set multicast time-to-live to 2...should keep our multicast packets from escaping the local network
            # self.multicast_socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)

            # Construct a membership request...tells router what multicast group we want to subscribe to
            membership_request = socket.inet_aton(MCAST_GRP) + socket.inet_aton(MCAST_IFACE)


            # Send add membership request to socket
            # See http://www.tldp.org/HOWTO/Multicast-HOWTO-6.html for explanation of sockopts
            # self.multicast_socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, str(membership_request))
            mreq = struct.pack('4sl', socket.inet_aton(MCAST_GRP), socket.INADDR_ANY)
            self.multicast_socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
                # Bind the socket to an interface.
            # If you bind to a specific interface on the Mac, no multicast data will arrive.
            # If you try to bind to all interfaces on Windows, no multicast data will arrive.
            # Hence the following.

            self.multicast_socket.bind(("", MCAST_PORT))

            # if self._id == 1:
            #     while True:
            #         self.multicast_socket.sendto(str.encode('test'), (MCAST_GRP, MCAST_PORT))
            # else:
            #     while True:
            #         print(self.multicast_socket.recv(10240))

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
        if self.GSID.value != message.gsid:
            self.log_error('Cannot deliver this message at this time')
            return

        # Process the message
        response_data, response_err = self.process_message(message.data)

        self.log_info('Delivered Message: {}'.format(message.mid))

        # Print the queue to console for debugging
        self.queue.qDisplay()

        # Update GSID
        with self.GSID.get_lock():
            self.GSID.value += 1

        with self.maxGSID.get_lock():
            self.maxGSID.value = max(self.maxGSID.value, self.GSID.value)

        # remove message from raw_message_buffer if it exists
        for idx, raw_msg in enumerate(self.raw_message_buffer):
            if raw_msg.mid == message.mid:
                self.raw_message_buffer.pop(idx)
                self.log_info('Removed msg({}) from raw_message_buffer'.format(raw_msg.mid))
                break

        # Check if we need to send a reply to the client
        if message.mid in self.from_client:
            original_client_message = self.from_client[message.mid]
            client_address = original_client_message.sender
            # change data to response
            message.data = response_data
            if response_err is not None:
                message.error = response_err
            # send reply to client
            self.unicast_message(message, client_address, MessageType.SERVER_CLIENT_REPLY)
            # Remove client message from buffer
            del self.from_client[message.mid]

        # Check if any other messages can be delivered
        if self.GSID.value in self.to_deliver:
            new_message = self.to_deliver[self.GSID.value]
            del self.to_deliver[self.GSID.value]
            self.deliver_message(new_message)

    def is_responsible_server(self, msg):
        """Returns true if this server is responsible for msg"""
        return self.config.is_responsible_server(msg)

    def get_responsible_server(self, msg):
        """Returns the ID of the responsible server for this message"""
        return self.config.get_responsible_server(msg)

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

    def handle_client_message(self, msg):
        """Handle messages received by clients"""
        self.log_info('Client Received msg: {} from: {}'.format(msg.mid, msg.sender))
        # Increment local message
        with self.counter.get_lock():
            self.counter.value += 1
        # Assign Message ID and sender address
        msg.mid = int(f'{self._id}0{self.counter.value}')
        # Add message to from_client buffer
        self.from_client[msg.mid] = msg
        # Multicast the message to all servers
        print('Sending multicast MID:', msg.mid)
        self.multicast_message(msg, MessageType.MULTICAST_RAW)
        # Check if self is responsible for this message
        if self.is_responsible_server(msg):
            # Issue global sequence number and multicast it
            self.handle_raw_multicast_message(msg)

    def request_retransmit_messages(self, is_config_mode=False):
        # Request for retransmissions
        for gsid in range(self.GSID.value, self.maxGSID.value + 1):
            if gsid not in self.to_deliver:
                msg = Message(
                    mid=-1,
                    data=self.GSID.value,
                )
                self.log_info('NACK for GSID: {}'.format(gsid))
                if is_config_mode:
                    self.multicast_message(msg, MessageType.SERVER_NACK, sender_type='config')
                else:
                    self.multicast_message(msg, MessageType.SERVER_NACK, sender_type='server')

    def handle_raw_multicast_message(self, msg: Message):
        """Checks if self is responsible, otherwise stores in raw_message buffer
        """
        if self.is_responsible_server(msg):
            # Check if missing any messages:
            if self.maxGSID.value != self.GSID.value:
                # Check for possible duplicates and store message in raw_message buffer
                if not any(x for x in self.raw_message_buffer if x.mid == msg.mid):
                    # self.log_info('Storing message: {} for future use.'.format(msg.mid))
                    self.raw_message_buffer.append(msg)
                self.request_retransmit_messages()
            else:
                # Issue the global sequence number to this message and multicast
                msg.gsid = self.GSID.value
                self.log_info('GSID {} Issued to message: {}'.format(self.GSID.value, msg.mid))
                msg.message_type = MessageType.MULTICAST_SEQUENCED
                self.delivered_messages[self.GSID.value] = msg
                self.multicast_message(msg, MessageType.MULTICAST_SEQUENCED)
                # Deliver the message locally.
                self.deliver_message(msg)
        else:
            # Check for possible duplicates and store message in raw_message buffer
            if not any(x for x in self.raw_message_buffer if x.mid == msg.mid):
                self.log_info('Storing message: {} for future use.'.format(msg.mid))
                self.raw_message_buffer.append(msg)

    def handle_sequenced_multicast_message(self, msg):
        # if expected GSID and message GSID match, deliver message
        if msg.gsid == self.GSID.value:
            # Deliver the message and update GSID
            self.deliver_message(msg)
        elif msg.gsid > self.GSID.value:
            # Add message to to_deliver buffer
            self.to_deliver[msg.gsid] = msg
            with self.maxGSID.get_lock():
                self.maxGSID.value = max(self.maxGSID.value, msg.gsid)
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
                if msg.sender_type == "config":
                    self.config_msg_buffer.put(msg)
                    return
                if msg.message_type == MessageType.CLIENT_REQUEST:
                    msg.sender = addr
                    self.raw_client_buffer.put(msg)
                elif msg.message_type == MessageType.SERVER_NACK_REPLY:
                    # Handle message received from NACK
                    self.handle_sequenced_multicast_message(msg)


            except Exception:
                self.log_exception('An error occurred while listening for messages...')

    def handle_multicast_recv(self):
        """Reads messages from muticast port, and process:
        """
        self.log_info('Listening for messages...')
        while True:
            try:
                if self.config_mode.value == ConfigStage.STABLE:
                    try:
                        self.multicast_socket.settimeout(None)
                        self.log_info('Waiting for new messages... {}'.format(self.multicast_socket))
                        data, addr = self.multicast_socket.recvfrom(self.BUFFERSIZE)
                        self.log_info('MulticastMsg: {}'.format(data.decode()))
                        self._process_multicast_recv(data, addr)
                    except socket.timeout:
                        self.log_info('No new messages...')
            except Exception:
                self.log_exception('An error occurred while listening for messages...')

    def _process_multicast_recv(self, data, addr):
        """Decode and process multicast receive messages
        """
        try:
            data = data.decode()
            msg = Message.from_string(data)
            self.log_info('Received Multicast Message: {}'.format(data))
            if msg.sender_type == "config" and msg.sender_id != self._id:
                if msg.message_type == MessageType.GROUP_SYNC:
                    with self.config_mode.get_lock():
                        self.config_mode.value = ConfigStage.WAIT_FOR_ACK
                self.config_msg_buffer.put(msg)
                return
            # Step 1: Add to  buffer
            if msg.sender_type == "server" and msg.sender_id != self._id:
                self.multicast_buffer.put(msg)
        except:
            self.log_info('Failed to decode multicast message: {}'.format(data))

    def unicast_message(self, msg, dest, msg_type, sender_type='server'):
        """Send a unicast message to provided destination
        """
        try:
            unicast_msg = Message(
                msg.mid, msg.data,
                sender=(self.HOST, self.PORT),
                gsid=msg.gsid,
                sender_id=self._id,
                sender_type=sender_type,
                message_type=msg_type,
                error= msg.error
            )
            msg_str = unicast_msg.to_string()
            self.unicast_socket.sendto(str.encode(msg_str), tuple(dest))
        except:
            self.log_exception('Failed to send unicast message: {}'.format(msg_str))


    def multicast_message(self, msg, msg_type, sender_type='server'):
        """Send a multicast message
        """
        try:
            multicast_msg = Message(
                msg.mid, msg.data,
                sender=(self.HOST, self.PORT),
                gsid=msg.gsid,
                sender_id=self._id,
                sender_type=sender_type,
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

        # Initiate Join Group Sequence
        group_sync_process = multiprocessing.Process(target=self.handle_group_sync, args=())
        group_sync_process.daemon = True
        group_sync_process.start()


        # Listen for multicast requests:
        multicast_process = multiprocessing.Process(target=self.handle_multicast_recv, args=())
        multicast_process.daemon = True
        multicast_process.start()

        with self.config_mode.get_lock():
            self.config_mode.value = ConfigStage.INIT

        self.multicast_socket.sendto(str.encode('test'), (MCAST_GRP, MCAST_PORT))

        while True:
            if self.config_mode.value != ConfigStage.STABLE:
                # if config buffer is not empty, get the top message in config buffer
                # IF message type is GROUP_SYNC -
                #   1) Switch to config mode
                #   2) multicast GROUP_SYNC_ACK with current GSID
                #   3) add sending server to config
                if not self.config_msg_buffer.empty():
                    config_msg = self.config_msg_buffer.get()
                    if config_msg.message_type == MessageType.GROUP_SYNC:
                        with self.config_mode.get_lock():
                            self.config_mode.value = ConfigStage.WAIT_FOR_ACK
                        self.config.reset_gsid()
                        self.send_group_sync_ack(MessageType.GROUP_SYNC_ACK)
                        self.config.add_server(config_msg.sender_id, config_msg.gsid,config_msg.sender)

                    elif config_msg.message_type == MessageType.GROUP_SYNC_ACK and \
                        self.config_mode.value == ConfigStage.WAIT_FOR_ACK:
                        if self.maxGSID.value < config_msg.gsid:
                            with self.maxGSID.get_lock():
                                self.maxGSID.value = max(self.maxGSID.value, config_msg.gsid)
                        self.config.add_server(config_msg.sender_id, config_msg.gsid, config_msg.sender)
                        if self.GSID.value < self.maxGSID.value:
                            self.request_retransmit_messages(is_config_mode=True)

                    elif config_msg.message_type == MessageType.GROUP_TRANSITION and \
                            self.config_mode.value == ConfigStage.WAIT_FOR_TRANSITION:
                        # compute new view id
                        self.config.view_id.set(self.config.compute_view_id())
                        # adding its own data to view
                        self.config.add_member(self._id,(self.HOST,self.PORT), self.GSID.value, self.config.view_id.get())
                        # adding sender's data
                        self.config.add_member(config_msg.sender_id,config_msg.sender, config_msg.gsid, int(config_msg.data))
                        self.config.server_data[self._id]['member_count'] = self.config.member_count.get()
                        # Acknowledge the message
                        self.send_group_sync_ack(MessageType.GROUP_TRANSITION_ACK)

                    elif config_msg.message_type == MessageType.GROUP_TRANSITION_ACK and \
                            self.config_mode.value == ConfigStage.WAIT_FOR_TRANSITION:
                        # adding sender's data
                        sender_view_id = int(config_msg.data[0])
                        sender_member_count = int(config_msg.data[1])
                        self.config.add_member(config_msg.sender_id,config_msg.sender, config_msg.gsid, sender_view_id)
                        self.config.server_data[config_msg.sender_id]['member_count'] = sender_member_count
                        # Update member count.
                        self.config.sender_data[self._id]['member_count'] = self.config.member_count.get()

                        # Transition to stable state when we have received everyone's member counts and they are equal.
                        if self.config.can_transition_to_stable():
                            with self.config_mode.get_lock():
                                self.config_mode.value = ConfigStage.STABLE
                            self.log_info('Transitioned to Stable, View id set to: {}, members: {}'.format(self.config.view_id.get(), self.config.member_count.get()))

                    elif config_msg.message_type == MessageType.SERVER_NACK:
                        # Send the previously sequenced message to server who sent NACK
                        gsid = int(config_msg.data)
                        self.log_info('Received NACK request for {}'.format(gsid))
                        if gsid in self.delivered_messages:
                            send_msg = self.delivered_messages[gsid]
                            self.log_info('Sending NACK reply for {}'.format(gsid))
                            self.unicast_message(send_msg, config_msg.sender, MessageType.SERVER_NACK_REPLY, sender_type='config')
                    elif config_msg.message_type == MessageType.SERVER_NACK_REPLY  and \
                        self.config_mode.value == ConfigStage.WAIT_FOR_ACK:
                        self.handle_sequenced_multicast_message(config_msg)
                        self.send_group_sync_ack(MessageType.GROUP_SYNC_ACK)

            elif self.config_mode.value == ConfigStage.STABLE:
                if not self.raw_client_buffer.empty():
                    # There is a message in the client buffer.
                    msg = self.raw_client_buffer.get()
                    self.log_info('Found client message: {}'.format(msg.to_string()))
                    self.handle_client_message(msg)

                # Process multicast message
                if not self.multicast_buffer.empty():
                    # There is a message in the multicast buffer.
                    msg = self.multicast_buffer.get()
                    self.log_info('Found multicast message: {}'.format(msg.to_string()))
                    # If receving a sequenced multicast message
                    if msg.has_gsid() and msg.message_type == MessageType.MULTICAST_SEQUENCED:
                        self.log_info('Processing sequenced multicast msg: self.gsid: {}, msg.ID:{}, msg.GSID: {}'.format(self.GSID.value, msg.mid, msg.gsid))
                        # Check if we can deliver or buffer it
                        self.handle_sequenced_multicast_message(msg)
                    elif msg.message_type == MessageType.MULTICAST_RAW:
                        self.log_info('Processing raw multicast msg: self.gsid: {}, msg.ID:{}, msg.GSID: {}'.format(self.GSID.value, msg.mid, msg.gsid))
                        # Check if self is responsible if so, issue GSID and multicast
                        # Otherwise, store message in raw_message buffer
                        self.handle_raw_multicast_message(msg)
                    elif msg.message_type == MessageType.SERVER_NACK:
                        # Send the previously sequenced message to server who sent NACK
                        gsid = int(msg.data)
                        self.log_info('Received NACK request for {}'.format(gsid))
                        if gsid in self.delivered_messages:
                            send_msg = self.delivered_messages[gsid]
                            self.log_info('Sending NACK reply for {}'.format(gsid))
                            self.unicast_message(send_msg, msg.sender, MessageType.SERVER_NACK_REPLY)
                if len(self.raw_message_buffer) > 0:
                    top_message = self.raw_message_buffer[0]
                    if self.get_responsible_server(top_message) == self.config.view_id.get() \
                            and self.GSID.value == self.maxGSID.value:
                        # Re-Sequence a message from buffer
                        self.log_info('Re-sequencing message: {}', top_message.mid)
                        self.handle_raw_multicast_message(self.raw_message_buffer.pop(0))
            time.sleep(1)

    def handle_group_sync(self):
        """Handles Group Synchronization
        """
        while True:
            if self.config_mode.value == ConfigStage.INIT:
                self.config.reset_gsid()
                self.config.add_server(self._id, (self.HOST,self.PORT), self.GSID.value)
                msg = Message(
                            mid=-1,
                            gsid=self.GSID.value,
                )
                self.multicast_message(msg, MessageType.GROUP_SYNC, sender_type='config')
                self.log_info('Sent GROUP SYNC message')
                with self.config_mode.get_lock():
                    self.config_mode.value = ConfigStage.WAIT_FOR_ACK
                    continue
            elif self.config_mode.value in [ConfigStage.WAIT_FOR_ACK, ConfigStage.WAIT_FOR_TRANSITION]:
                retry_limit = 1
                reply_count = 0

                while retry_limit < 3 and self.config_mode.value in [ConfigStage.WAIT_FOR_ACK, ConfigStage.WAIT_FOR_TRANSITION]:
                    try:
                        ## Wait for reply for 3 seconds to 6 seconds
                        self.multicast_socket.settimeout(3 * retry_limit)
                        self.log_info('Waiting.... {}'.format(self.multicast_socket))
                        data, addr = self.multicast_socket.recvfrom(self.BUFFERSIZE)
                        self.log_info('MulticastMsg: {}'.format(data.decode()))
                        reply_count += 1
                        self._process_multicast_recv(data, addr)
                    except socket.timeout:
                        retry_limit += 1
                        if reply_count == 0:
                            self.log_info('No reply received within timeout... retrying..')
                            self.send_group_sync_ack(MessageType.GROUP_SYNC_ACK)

                self.multicast_socket.settimeout(None)
                if retry_limit >= 3 and reply_count == 0:
                    self.log_info('No reply received within timeout... Assuming sole server')
                    self.config.view_id.set(self.config.compute_view_id())
                    view_id = self.config.add_member(self._id,(self.HOST,self.PORT), self.GSID.value, self.config.view_id.get())
                    with self.config_mode.get_lock():
                        self.config_mode.value = ConfigStage.STABLE
                        self.log_info('View id set to: {}'.format(view_id))
                        self.multicast_socket.settimeout(None)
                    continue


                # timer Runs out and you are in WAIT_FOR_ACK mode and have received some replies.
                if not config.can_transition():
                    max_gsid = self.config.get_max_gsid()
                    #timer reset on every new message that is recieved
                    if self.GSID.value < max_gsid:
                        with self.maxGSID.get_lock():
                            self.maxGSID.value = max(self.maxGSID.value, max_gsid)
                        # process messages currently in buffer
                        self.request_retransmit_messages(is_config_mode=True)
                        self.send_group_sync_ack(MessageType.GROUP_SYNC_ACK)

                else:
                    # When timer runs out and we can transition
                    with self.config_mode.get_lock():
                        self.config_mode.value = ConfigStage.WAIT_FOR_TRANSITION
                    #  Reset the view IDs here.
                    self.config.reset_view_ids()
                    #check if it is the leader
                    if self.config.is_leader():
                        self.config.view_id.set(self.config.compute_view_id())
                        self.config.add_member(self._id, (self.HOST,self.PORT), self.GSID.value, self.config.view_id.get())
                        self.config.server_data[self._id]['member_count'] = self.config.member_count.get()
                        msg = Message(
                            mid=-1,
                            data=self.config.view_id.get(),
                            gsid=self.GSID.value,
                        )
                        self.multicast_message(msg,MessageType.GROUP_TRANSITION, sender_type="config")

    def send_group_sync_ack(self,msg_type):
        if msg_type == MessageType.GROUP_SYNC_ACK:
            msg = Message(
                mid=-1,
                gsid=self.GSID.value,
            )
        elif msg_type == MessageType.GROUP_TRANSITION_ACK:
            msg = Message(
                mid=-1,
                data=(self.config.view_id.get(), self.config.member_count.get()),
                gsid=self.GSID.value,
            )
        self.multicast_message(msg,msg_type, sender_type="config")



        while True:
            if not self.multicast_buffer.empty():
                # There is a message in the multicast buffer.
                msg = self.multicast_buffer.get()
                self.log_info('Found multicast message: {}'.format(msg.to_string()))
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
                elif msg.message_type == MessageType.SERVER_NACK:
                    # Send the previously sequenced message to server who sent NACK
                    gsid = int(msg.data)
                    self.log_debug('Received NACK request for {}'.format(gsid))
                    if gsid in self.delivered_messages:
                        send_msg = self.delivered_messages[gsid]
                        self.log_debug('Sending NACK reply for {}'.format(gsid))
                        self.unicast_message(send_msg, msg.sender, MessageType.SERVER_NACK_REPLY)
            if len(self.raw_message_buffer) > 0:
                top_message = self.raw_message_buffer[0]
                if self.get_responsible_server(top_message) == self._id \
                        and self.GSID.value == self.maxGSID.value:
                    # Re-Sequence a message from buffer
                    self.log_debug('Re-sequencing message: {}', top_message.m_id)
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

    args = parser.parse_args()
    local_ip = get_local_ip()
    print('localIp: ', local_ip)
    MCAST_IFACE = local_ip
    server = UDPServer(args.id, args.host, args.port)
    server.listen()
