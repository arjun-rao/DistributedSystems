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
from multiprocessing import SimpleQueue, Manager, Lock

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
        self.BUFFERSIZE = 8024
        self.manager = Manager()
        self.lock = Lock()
        self.config = Config(self.manager, self.lock, self._id)

        # Server's FTQueue
        self.queue = FTQueue(self.manager, self.lock)

        self.timer_sync = multiprocessing.Value('i', 1)
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
                self.multicast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            self.multicast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)


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
                break

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
            is_config_mode = self.config_mode.value != ConfigStage.STABLE
            self.request_retransmit_messages(is_config_mode = True)

    def handle_unicast_recv(self):
        """Reads messages from client, and process:
            1) Assign message ID - f'{SID}0{self.counter}'
            2) Multicast message
            3) Move to from_client buffer
        """
        self.log_info('Started Deamon Process')
        while True:
            try:
                try:
                    self.unicast_socket.settimeout(1)
                    data, addr = self.unicast_socket.recvfrom(self.BUFFERSIZE)
                    data = data.decode()
                    msg = Message.from_string(data)
                    print('Unicast Recv: {} {}', MessageType(msg.message_type).name, msg.data)
                except:
                    # print('No unicast message...')
                    time.sleep(1)
                    continue

                if msg.sender_type == "config":
                    print('Unicast Config: {} {}', MessageType(msg.message_type).name, msg.data)
                    self.config_msg_buffer.put(msg)
                    continue
                if msg.message_type == MessageType.CLIENT_REQUEST:
                    msg.sender = addr
                    self.raw_client_buffer.put(msg)
                elif msg.message_type == MessageType.SERVER_NACK_REPLY:
                    # Handle message received from NACK
                    self.handle_sequenced_multicast_message(msg)
                elif msg.message_type == MessageType.REQUEST_QUEUE_STATE:
                    reply_msg = Message(
                        mid = -1,
                        data = (self.queue.get_queue_state(), self.maxGSID.value),
                        gsid = self.GSID.value
                    )
                    self.unicast_message(reply_msg, addr, MessageType.REQUEST_QUEUE_STATE_ACK, sender_type = 'config')
                elif msg.message_type == MessageType.UPDATE_QUEUE_STATE:
                    with self.GSID.get_lock():
                        self.GSID.value = msg.gsid
                    with self.maxGSID.get_lock():
                        self.maxGSID.value = msg.data[1]
                    self.queue.update_queue_state(msg.data[0])
                    reply_msg = Message(
                        mid = -1,
                        gsid = self.GSID.value
                    )
                    self.unicast_message(reply_msg, addr, MessageType.UPDATE_QUEUE_STATE_ACK, sender_type = 'config')
                    while True:
                        try:
                            self.unicast_socket.settimeout(3)
                            data2, new_addr = self.unicast_socket.recvfrom(self.BUFFERSIZE)
                            data2 = data2.decode()
                            ack_msg = Message.from_string(data2)
                            if ack_msg.message_type == MessageType.UPDATE_QUEUE_STATE_ACK:
                                break
                        except socket.timeout:
                                self.unicast_message(reply_msg, addr, MessageType.UPDATE_QUEUE_STATE_ACK, sender_type = 'config')
                                continue
            except Exception:
                self.log_exception('An error occurred while listening for messages...')

    def handle_multicast_recv(self):
        """Reads messages from muticast port, and process:
        """
        self.log_info('Listening for messages...')
        while True:
            try:
                with self.config_mode.get_lock():
                    config_mode = self.config_mode.value

                if config_mode not in [ConfigStage.WAIT_FOR_ACK, ConfigStage.WAIT_FOR_TRANSITION]:
                    try:
                        self.multicast_socket.settimeout(1)
                        data, addr = self.multicast_socket.recvfrom(self.BUFFERSIZE)
                        # self.log_info('MulticastMsg: {}'.format(data.decode()))
                        self._process_multicast_recv(data, addr)
                    except socket.timeout:
                        # self.log_info('No new messages...')
                        pass
                else:
                    time.sleep(1)
            except Exception:
                self.log_exception('An error occurred while listening for messages...')

    def sync_queue_state(self, master_server_addr):
        """Send unicast message to server_addr, and request updated queue state.
           Once a reply is received, send unicast messages to all members in self.config.server_data excluding self.
           Once acknowledgements are received from all members send "Partition Resolved" message to server_addr
        """
        msg = Message(
                mid = -1,
                gsid = self.GSID.value
        )
        self.log_info('Sent Request Queue State')
        self.unicast_message(msg,master_server_addr,MessageType.REQUEST_QUEUE_STATE,sender_type='config')
        update_queue_ack_counter = 1
        while True:
            try:
                try:
                    self.unicast_socket.settimeout(3)
                    data, addr = self.unicast_socket.recvfrom(self.BUFFERSIZE)
                    data = data.decode()
                    msg = Message.from_string(data)
                except socket.timeout:
                    continue
                # TODO: Check if reply received for queue state. If so, send unicast messages to all
                if msg.message_type == MessageType.REQUEST_QUEUE_STATE_ACK:
                    self.log_info('Received Request Queue Ack')
                    with self.GSID.get_lock():
                        self.GSID.value = msg.gsid
                    with self.maxGSID.get_lock():
                        self.maxGSID.value = msg.data[1]
                    self.queue.update_queue_state(msg.data[0])
                    self.log_info('Updated Queue State:')
                    self.queue.qDisplay()
                    for keys,values in self.config.server_data.items():
                        if values['addr']  != self._addr:
                            server_addr = values['addr']
                            update_msg = Message(
                                mid = -1,
                                data = msg.data,
                                gsid = msg.gsid,
                            )
                            self.unicast_message(update_msg,server_addr,MessageType.UPDATE_QUEUE_STATE, sender_type = 'config')

                        elif msg.message_type == MessageType.UPDATE_QUEUE_STATE_ACK:
                            # count the number of such replies received. if it is equal to en(self.config.server_data.keys())
                            # then send partition resolved as multicast
                            update_queue_ack_counter += 1
                            self.unicast_message(msg, addr, MessageType.UPDATE_QUEUE_STATE_ACK, sender_type = 'config')
                            if update_queue_ack_counter == len(self.config.server_data.keys()):
                                ack_msg = Message(
                                    mid = -1,
                                    gsid =self.GSID.value
                                )
                                self.log_info('Partition Resolved, Will Start Group Sync...')
                                self.multicast_message(ack_msg, MessageType.PARTITION_RESOLVED, sender_type = 'config')
                                time.sleep(2)
                                self.start_group_sync()
            except Exception:
                    self.log_exception('An error occurred while listening for messages...')

    def _process_multicast_recv(self, data, addr):
        """Decode and process multicast receive messages
        """
        try:
            data = data.decode()
            msg = Message.from_string(data)
            if msg.sender_id != self._id:
                self.log_info('Recvd MM({}): {} with data: {}'.format(msg.config_id,MessageType(msg.message_type).name, (msg.gsid, msg.data)))
                self.log_info('Current config: {}, iD: {}'.format(
                    ConfigStage(self.config_mode.value).name,
                    self.config.config_id.get())
                )
                if msg.message_type == MessageType.PARTITION_DETECTED:
                    self.log_info('Partition Detect Received - Switching to Wait for partition resolve')
                    with self.config_mode.get_lock():
                        self.config_mode.value = ConfigStage.WAIT_FOR_PARTITION_RESOLVE
                    # empty config buffer
                    while not self.config_msg_buffer.empty():
                        self.config_msg_buffer.get()
                    return
                elif msg.message_type == MessageType.PARTITION_RESOLVED:
                    self.log_info('Partition Resolved - Waiting for Next Group Sync...')
                    self.config.set_force_sync()
                    with self.config_mode.get_lock():
                        self.config_mode.value = ConfigStage.UNKNOWN
                    return
                # Add elif for Partition Resolved, switch to UKNOWN config and call self.config.set_force_sync().


                if msg.sender_type =='config' and msg.message_type == MessageType.GROUP_SYNC:
                    with self.config.lock:
                        member_count = self.config.member_count.get()
                    if self.config.should_force_sync():
                        # empty config buffer
                        while not self.config_msg_buffer.empty():
                            self.config_msg_buffer.get()
                        with self.config_mode.get_lock():
                            self.config_mode.value = ConfigStage.UNKOWN
                        self.config.clear_force_sync()
                        self.config_msg_buffer.put(msg)
                        return 1
                    # Check if Group Sync is coming from another partition.
                    elif msg.data[1] != member_count and msg.data[1] != 0 and member_count != 0:
                        if self.config.is_leader():
                            self.log_info('Partition Detected: self({}) != {}'.format(member_count, msg.data[1]))
                            # empty config buffer
                            while not self.config_msg_buffer.empty():
                                self.config_msg_buffer.get()
                            partition_msg = Message(
                                mid=-1,
                                gsid=self.GSID.value,
                            )
                            self.log_info('Sent Partition Detected')
                            self.multicast_message(partition_msg, MessageType.PARTITION_DETECTED, sender_type='config')
                            self.sync_queue_state(msg.sender)
                            # set force sync to make sure next Group Sync is processed.
                            self.config.set_force_sync()
                            return -1

                if self.config_mode.value == ConfigStage.STABLE:
                    if msg.sender_type =='config' and msg.message_type == MessageType.GROUP_SYNC:
                        # Same partition or new member
                        if msg.sender_id in self.config.server_data.keys() or msg.data[1] == 0:
                            # empty config buffer
                            while not self.config_msg_buffer.empty():
                                self.config_msg_buffer.get()
                            with self.config_mode.get_lock():
                                self.config_mode.value = ConfigStage.UNKOWN
                            self.config_msg_buffer.put(msg)
                            return 1
                    elif msg.sender_type =='config' and msg.config_id != self.config.config_id.get():
                        with self.config_mode.get_lock():
                            self.config_mode.value = ConfigStage.INIT
                        return -1
                    elif msg.sender_type == "server" and msg.sender_id != self._id:
                        if self.config.config_id.get() == msg.config_id:
                            self.multicast_buffer.put(msg)
                            return 1
                        else:
                            # Start Group Sync as you received out of context messages
                            time.sleep(self._id * 5)
                            with self.config_mode.get_lock():
                                self.config_mode.value = ConfigStage.INIT
                            return -1
                    elif msg.sender_type == "config" and self.config.config_id.get() == msg.config_id:
                        # if msg.message_type == MessageType.GROUP_TRANSITION_ACK:
                        #     if msg.data[1] != self.config.member_count.get():
                        #         with self.config_mode.get_lock():
                        #             self.config_mode.value = ConfigStage.INIT
                        #         return -1
                        #     if self.config.is_leader():
                        #         msg = Message(
                        #             mid=-1,
                        #             data=self.config.get_transition_data(),
                        #             gsid=self.GSID.value,
                        #         )
                        #         self.multicast_message(msg,MessageType.GROUP_TRANSITION, sender_type="config")
                        #         self.log_info('ReSent Group Transition, view_id: {}'.format(self.config.view_id.get()))
                        #         self.log_info('ServerData: {}'.format(self.config.server_data))
                        #         self.log_info('Views: {}'.format(self.config.server_view))
                        #     else:
                        #         self.send_group_sync_ack(MessageType.GROUP_TRANSITION_ACK)
                        return 1
                else:
                    if msg.sender_type == "config" and self.config.config_id.get() == msg.config_id:
                        self.config_msg_buffer.put(msg)
                        return 1
                    else:
                        # Start Group Sync as you received out of context messages
                        if msg.message_type == MessageType.GROUP_SYNC:
                            if msg.sender_id in self.config.server_data.keys() or msg.data[1] == 0:
                                with self.config_mode.get_lock():
                                    self.config_mode.value = ConfigStage.UNKOWN
                                self.config_msg_buffer.put(msg)
                        return -1

        except Exception:
            self.log_exception('Failed to decode multicast message: {}'.format(data))
        print('Returning False')
        self.log_info('After MM({}): {} with data: {}'.format(msg.config_id,MessageType(msg.message_type).name, (msg.gsid, msg.data)))
        return False

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
                error= msg.error,
                config_id=self.config.config_id.get()
            )
            msg_str = unicast_msg.to_string()
            self.unicast_socket.sendto(str.encode(msg_str), tuple(dest))
        except:
            self.log_exception('Failed to send unicast message: {}'.format(msg_str))


    def multicast_message(self, msg, msg_type, sender_type='server'):
        """Send a multicast message
        """

        try:
            with self.config.lock:
                config_id = self.config.config_id.get()
            multicast_msg = Message(
                msg.mid, msg.data,
                sender=(self.HOST, self.PORT),
                gsid=msg.gsid,
                sender_id=self._id,
                sender_type=sender_type,
                message_type=msg_type,
                error=msg.error,
                config_id=config_id
            )
            if sender_type == 'config':
                self.log_info('Send T: {}, C: {}'.format(MessageType(msg_type).name, multicast_msg.config_id))
            msg_str = multicast_msg.to_string()
            self.multicast_socket.sendto(str.encode(msg_str), (MCAST_GRP, MCAST_PORT))
        except:
            self.log_exception('Failed to multicast message: {}'.format(msg_str))

    def add_member_from_msg(self, config_msg):
        """Adds a sender to view"""
        # adding sender's data
        print('data: ', config_msg.data, 'type:', type(config_msg.data))
        sender_view_id = int(config_msg.data[0])
        sender_member_count = int(config_msg.data[1])
        self.config.add_member(config_msg.sender_id,config_msg.sender, config_msg.gsid, sender_view_id)
        # Update sender's data
        self.config.server_data[config_msg.sender_id]['member_count'] = sender_member_count
        with self.lock:
            data = self.config.server_data[config_msg.sender_id]
            data['member_count'] = sender_member_count
            self.config.server_data[config_msg.sender_id] = data
        # Update member count.
        with self.lock:
            data = self.config.server_data[self._id]
            data['member_count'] = self.config.member_count.get()
            self.config.server_data[self._id] = data
        self.log_info('ServerData: {}'.format(self.config.server_data))
        self.log_info('Views: {}'.format(self.config.server_view))


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


        # Timer for Sync
        timer_sync_process = multiprocessing.Process(target=self.handle_timer_sync, args=())
        timer_sync_process.daemon = True
        timer_sync_process.start()


        with self.config_mode.get_lock():
            self.config_mode.value = ConfigStage.INIT



        while True:
            if self.config_mode.value != ConfigStage.STABLE:
                # if config buffer is not empty, get the top message in config buffer
                # IF message type is GROUP_SYNC -
                #   1) Switch to config mode
                #   2) multicast GROUP_SYNC_ACK with current GSID
                #   3) add sending server to config
                if not self.config_msg_buffer.empty():
                    config_msg = self.config_msg_buffer.get()
                    self.log_info('ConfigID: {}'.format(self.config.config_id.get()))
                    self.log_info('ConfigMode: {}'.format(ConfigStage(self.config_mode.value).name))
                    self.log_info('Processing MM({}): {} with data: {}'.format(config_msg.config_id,MessageType(config_msg.message_type).name, (config_msg.gsid, config_msg.data)))
                    with self.config_mode.get_lock():
                        config_mode = self.config_mode.value
                    if config_msg.message_type == MessageType.GROUP_SYNC:
                        while not self.config_msg_buffer.empty():
                            self.config_msg_buffer.get()
                        with self.config.lock:
                            self.config.config_id.set(config_msg.config_id)
                        self.config.reset_gsid()
                        with self.config_mode.get_lock():
                            self.config_mode.value = ConfigStage.WAIT_FOR_ACK
                        self.send_group_sync_ack(MessageType.GROUP_SYNC_ACK)
                        self.config.add_server(self._id, (self.HOST,self.PORT), self.GSID.value)
                        self.config.add_server(config_msg.sender_id, config_msg.sender, config_msg.gsid)
                        self.log_info('Start Sync ServerData: {}'.format(self.config.server_data))
                        self.log_info('Config: {}'.format(ConfigStage(self.config_mode.value).name))

                    elif config_msg.message_type == MessageType.GROUP_SYNC_ACK and \
                        config_mode == ConfigStage.WAIT_FOR_ACK:
                        if self.maxGSID.value < config_msg.gsid:
                            with self.maxGSID.get_lock():
                                self.maxGSID.value = max(self.maxGSID.value, config_msg.gsid)
                        self.config.add_server(config_msg.sender_id, config_msg.sender, config_msg.gsid)
                        self.log_info('After Update: ServerData: {}'.format(self.config.server_data))
                        self.log_info('Views: {}'.format(self.config.server_view))
                        if self.GSID.value < self.maxGSID.value:
                            with self.config_mode.get_lock():
                                self.config_mode.value = ConfigStage.WAIT_FOR_NACK
                            self.request_retransmit_messages(is_config_mode=True)

                        # if self.config.can_transition():
                        #         self.handle_shift_to_transition()
                        # else:
                        #     continue

                    elif config_msg.message_type == MessageType.GROUP_TRANSITION:

                        self.log_info('Got Transition Message')
                        # compute new view id
                        self.config.load_transition_data(config_msg.data)
                        self.log_info('Loaded Transition Data')

                        with self.config_mode.get_lock():
                            self.config_mode.value = ConfigStage.STABLE
                        while not self.config_msg_buffer.empty():
                            self.config_msg_buffer.get()
                        self.log_info('Transitioned to Stable, View id set to: {}, members: {}'.format(self.config.view_id.get(), self.config.member_count.get()))
                        self.log_info('Queue: {}'.format(self.queue.get_queue_state()))
                        continue

                    elif config_msg.message_type == MessageType.GROUP_TRANSITION_ACK:
                        if config_mode != ConfigStage.WAIT_FOR_TRANSITION:
                            if self.config.can_transition():
                                self.handle_shift_to_transition()
                            else:
                                continue

                    #     if not self.config.has_member(config_msg.sender_id):
                    #         self.add_member_from_msg(config_msg)
                    #         self.send_group_sync_ack(MessageType.GROUP_TRANSITION_ACK)
                    #     # Transition to stable state when we have received everyone's member counts and they are equal.
                    #     if self.config.can_transition_to_stable():
                    #         with self.config_mode.get_lock():
                    #             self.config_mode.value = ConfigStage.STABLE
                    #         while not self.config_msg_buffer.empty():
                    #             self.config_msg_buffer.get()
                    #         self.log_info('Transitioned to Stable, View id set to: {}, members: {}'.format(self.config.view_id.get(), self.config.member_count.get()))
                    #         self.log_info('Queue: {}'.format(self.queue.get_queue_state()))
                    #         continue

                    elif config_msg.message_type == MessageType.SERVER_NACK:
                        # Send the previously sequenced message to server who sent NACK
                        gsid = int(config_msg.data)
                        self.log_info('Received NACK request for {}'.format(gsid))
                        if gsid in self.delivered_messages:
                            send_msg = self.delivered_messages[gsid]
                            self.unicast_message(send_msg, config_msg.sender,
                                MessageType.SERVER_NACK_REPLY, sender_type='config')
                            self.log_info('Sent NACK reply for {}'.format(gsid))
                        with self.config_mode.get_lock():
                                self.config_mode.value = ConfigStage.WAIT_FOR_NACK

                    elif config_msg.message_type == MessageType.GROUP_NACK_COMPLETE and \
                        self.config_mode.value == ConfigStage.WAIT_FOR_NACK:
                        with self.config_mode.get_lock():
                            self.config_mode.value = ConfigStage.WAIT_FOR_ACK
                        self.config.add_server(config_msg.sender_id, config_msg.sender, config_msg.gsid)
                        self.send_group_sync_ack(MessageType.GROUP_SYNC_ACK)
                        if self.config.can_transition():
                            self.handle_shift_to_transition()
                        else:
                            continue

                    elif config_msg.message_type == MessageType.SERVER_NACK_REPLY  and \
                        self.config_mode.value == ConfigStage.WAIT_FOR_NACK:
                        self.handle_sequenced_multicast_message(config_msg)
                        if self.GSID.value == self.maxGSID.value:
                            self.send_group_sync_ack(MessageType.GROUP_NACK_COMPLETE)
                            self.start_group_sync()
                        else:
                            if self.GSID.value < self.maxGSID.value:
                                with self.config_mode.get_lock():
                                    self.config_mode.value = ConfigStage.WAIT_FOR_NACK
                                self.request_retransmit_messages(True)

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

    def handle_timer_sync(self):
        """Handles periodic timer synchronization
        """
        while True:
            # check every minute
            with self.config_mode.get_lock():
                config_mode = self.config_mode.value
            if config_mode == ConfigStage.STABLE:
                with self.timer_sync.get_lock():
                    sync_val = self.timer_sync.value
                if sync_val == 1:
                    self.log_info('Config Mode is stable, timer will start sync after 1 minute...')
                    time.sleep(120 +  5 * self._id)
                    with self.timer_sync.get_lock():
                        self.timer_sync.value = 0
                    continue
                self.log_info('Resetting config...')
                self.start_group_sync()
                with self.timer_sync.get_lock():
                    self.timer_sync.value = 1
            # elif config_mode in [ConfigStage.WAIT_FOR_ACK, ConfigStage.WAIT_FOR_TRANSITION]:
            #     if config_mode == ConfigStage.WAIT_FOR_ACK:
            #         if self.config.can_transition():
            #             self.handle_shift_to_transition()
            #         else:
            #             self.send_group_sync_ack(MessageType.GROUP_SYNC_ACK)
            #     else:
            #         self.send_group_sync_ack(MessageType.GROUP_TRANSITION_ACK)
            else:
                self.log_info('No changes to config needed...')
                time.sleep(120 +  5 * self._id)

    def start_group_sync(self):
        # Get member count before Sync
        with self.config.lock:
            prev_group_member_count = self.config.member_count.get()
        self.config.reset_gsid()
        self.config.reset_view_ids()
        # empty config buffer
        while not self.config_msg_buffer.empty():
            self.config_msg_buffer.get()
        self.config.add_server(self._id, (self.HOST,self.PORT), self.GSID.value)
        config_id = self.config.generate_config_id()
        with self.config.lock:
            self.config.config_id.set(config_id)
        msg = Message(
                    mid=-1,
                    data=(config_id, prev_group_member_count),
                    gsid=self.GSID.value,
        )
        self.multicast_message(msg, MessageType.GROUP_SYNC, sender_type='config')
        self.log_info('Sent GROUP SYNC message')
        self.log_info('ServerData: {}'.format(self.config.server_data))
        self.log_info('Views: {}'.format(self.config.server_view))
        with self.config_mode.get_lock():
            self.config_mode.value = ConfigStage.WAIT_FOR_ACK


    def handle_group_sync(self):
        """Handles Group Synchronization
        """
        while True:
            with self.config_mode.get_lock():
                config_mode = self.config_mode.value
            if config_mode == ConfigStage.INIT:
                # Get member count before Sync
                with self.config.lock:
                    prev_group_member_count = self.config.member_count.get()
                self.config.reset_gsid()
                self.config.reset_view_ids()
                # empty config buffer
                while not self.config_msg_buffer.empty():
                    self.config_msg_buffer.get()
                self.config.add_server(self._id, (self.HOST,self.PORT), self.GSID.value)
                config_id = self.config.generate_config_id()
                with self.config.lock:
                    self.config.config_id.set(config_id)
                msg = Message(
                            mid=-1,
                            data=(config_id, prev_group_member_count),
                            gsid=self.GSID.value,
                )
                self.multicast_message(msg, MessageType.GROUP_SYNC, sender_type='config')
                self.log_info('Sent GROUP SYNC message')
                self.log_info('ServerData: {}'.format(self.config.server_data))
                self.log_info('Views: {}'.format(self.config.server_view))

                with self.config_mode.get_lock():
                    self.config_mode.value = ConfigStage.WAIT_FOR_ACK
                    continue
            else:
                with self.config_mode.get_lock():
                    config_mode = self.config_mode.value
                if config_mode in [ConfigStage.WAIT_FOR_ACK, ConfigStage.WAIT_FOR_TRANSITION, ConfigStage.UNKOWN]:
                    self.log_info('Listen Config: {}'.format(ConfigStage(self.config_mode.value).name))
                    retry_limit = 1
                    reply_count = 0
                    self.log_info('Listening for Sync Messages')
                    with self.config_mode.get_lock():
                        config_mode = self.config_mode.value
                    while (retry_limit < 3 and config_mode == ConfigStage.WAIT_FOR_ACK) or \
                            (retry_limit <  5 and config_mode == ConfigStage.WAIT_FOR_TRANSITION) or (config_mode == ConfigStage.UNKOWN):
                        try:
                            ## Wait for reply for 3 seconds to 6 seconds
                            self.multicast_socket.settimeout(3 * retry_limit)
                            self.log_info('Wait for ACK/TACK... {}'.format(ConfigStage(config_mode).name))
                            data, addr = self.multicast_socket.recvfrom(self.BUFFERSIZE)
                            # self.log_info('MulticastMsg: {}'.format(data.decode()))

                            if self._process_multicast_recv(data, addr) == 1:
                                reply_count += 1
                            else:
                                with self.config_mode.get_lock():
                                    if self.config_mode.value not in [ConfigStage.WAIT_FOR_ACK, ConfigStage.WAIT_FOR_TRANSITION]:
                                        break
                        except socket.timeout:
                            time.sleep(1)
                            self.log_info('ACK/TACK timeout....')
                            with self.config_mode.get_lock():
                                if self.config_mode.value not in [ConfigStage.WAIT_FOR_ACK, ConfigStage.WAIT_FOR_TRANSITION]:
                                    break
                            retry_limit += 1
                            if self.config_mode.value == ConfigStage.WAIT_FOR_TRANSITION:
                                if self.config.is_leader():
                                    self.handle_shift_to_transition()
                                # else:
                                    # self.send_group_sync_ack(MessageType.GROUP_TRANSITION_ACK)
                            else:
                                self.send_group_sync_ack(MessageType.GROUP_SYNC_ACK)
                            if reply_count == 0:
                                self.log_info('No reply received within timeout... retrying..')
                                if self.config_mode.value == ConfigStage.WAIT_FOR_ACK :
                                    self.send_group_sync_ack(MessageType.GROUP_SYNC_ACK)
                                elif self.config_mode.value == ConfigStage.WAIT_FOR_TRANSITION:
                                    self.handle_shift_to_transition()

                    with self.config_mode.get_lock():
                        if self.config_mode.value not in [ConfigStage.WAIT_FOR_ACK, ConfigStage.WAIT_FOR_TRANSITION]:
                            continue
                    self.multicast_socket.settimeout(None)
                    if self.config_mode.value == ConfigStage.WAIT_FOR_TRANSITION and retry_limit >= 5:
                        with self.config_mode.get_lock():
                            self.config_mode.value = ConfigStage.INIT
                    if reply_count == 0 and self.config_mode.value == ConfigStage.WAIT_FOR_ACK:
                        self.config.reset_gsid()
                        self.config.reset_view_ids()
                        self.config.add_server(self._id, (self.HOST,self.PORT), self.GSID.value)
                        config_id = self.config.generate_config_id()
                        with self.config.lock:
                            self.config.config_id.set(config_id)
                        self.log_info('No reply received within timeout...')
                        self.log_info('Assuming sole server')
                        self.config.view_id.set(self.config.compute_view_id())
                        view_id = self.config.add_member(self._id,(self.HOST,self.PORT), self.GSID.value, self.config.view_id.get())
                        with self.config_mode.get_lock():
                            self.config_mode.value = ConfigStage.STABLE
                            while not self.config_msg_buffer.empty():
                                self.config_msg_buffer.get()
                            self.log_info('View id set to: {}'.format(view_id))
                            self.multicast_socket.settimeout(None)
                        continue
                    self.log_info('ReplyCount: {}'.format(reply_count))
                    self.log_info('ConfigMode: {}'.format(ConfigStage(self.config_mode.value).name))
                    with self.GSID.get_lock():
                        with self.lock:
                            data = self.config.server_data[self._id]
                            data['gsid'] = self.GSID.value
                            self.config.server_data[self._id] = data
                    if not self.config.can_transition():
                        max_gsid, min_key = self.config.get_max_gsid()
                        self.log_info('Cannot transition, S:{} has GSID: {}, MAX: {}'.format(min_key[0], min_key[1], max_gsid))
                        #timer reset on every new message that is recieved
                        if self.GSID.value < max_gsid:
                            with self.maxGSID.get_lock():
                                self.maxGSID.value = max(self.maxGSID.value, max_gsid)
                            # process messages currently in buffer
                            self.request_retransmit_messages(is_config_mode=True)
                            self.send_group_sync_ack(MessageType.GROUP_SYNC_ACK)
                    else:
                        self.handle_shift_to_transition()
            # time.sleep(1)

    def handle_shift_to_transition(self):
         # When timer runs out and we can transition
        if self.config.can_transition():
            with self.config_mode.get_lock():
                self.config_mode.value = ConfigStage.WAIT_FOR_TRANSITION
            self.log_info('Checking Leader: {}'.format(self.config.is_leader()))
            #check if it is the leader
            if self.config.is_leader():
                #  Reset the view IDs here.
                self.config.reset_view_ids()
                with self.lock:
                    self.config.view_id.set(0)
                self.config.add_member(self._id, (self.HOST,self.PORT), self.GSID.value, self.config.view_id.get())
                next_view_id = 1
                for key, data in self.config.server_data.items():
                    if key == self._id:
                        continue
                    self.config.add_member(key,data['addr'], data['gsid'], next_view_id)
                    next_view_id += 1
                with self.lock:
                    data = self.config.server_data[self._id]
                    data['member_count'] = self.config.member_count.get()
                    self.config.server_data[self._id] = data
                msg = Message(
                    mid=-1,
                    data=self.config.get_transition_data(),
                    gsid=self.GSID.value,
                )
                self.log_info('Transition Data: {}'.format(msg.data))
                self.multicast_message(msg,MessageType.GROUP_TRANSITION, sender_type="config")
                self.log_info('Sent Group Transition, view_id: {}'.format(self.config.view_id.get()))
                self.log_info('ServerData: {}'.format(self.config.server_data))
                self.log_info('Views: {}'.format(self.config.server_view))
                with self.config_mode.get_lock():
                    self.config_mode.value = ConfigStage.STABLE
                while not self.config_msg_buffer.empty():
                    self.config_msg_buffer.get()
                self.log_info('Transitioned to Stable, View id set to: {}, members: {}'.format(self.config.view_id.get(), self.config.member_count.get()))
                self.log_info('Queue: {}'.format(self.queue.get_queue_state()))
                return True
            else:
                self.send_group_sync_ack(MessageType.GROUP_TRANSITION_ACK)
            return True
        else:
            return False

    def send_group_sync_ack(self,msg_type):
        if msg_type == MessageType.GROUP_SYNC_ACK or msg_type == MessageType.GROUP_NACK_COMPLETE:
            msg = Message(
                mid=-1,
                gsid=self.GSID.value,
            )
            self.log_info('Sending {} with data: {}'.format(MessageType(msg_type).name, msg.gsid))
        elif msg_type == MessageType.GROUP_TRANSITION_ACK:
            msg = Message(
                mid=-1,
                data=(self.config.view_id.get(), self.config.member_count.get()),
                gsid=self.GSID.value,
            )
            self.log_info('Sending {} with data: {}'.format(MessageType(msg_type).name, msg.data))
        self.multicast_message(msg,msg_type, sender_type="config")

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
    # if args.id % 2 == 0:
    #     MCAST_GRP = '224.1.1.1'
    # else:
    #     MCAST_GRP = '224.1.1.2'
    server = UDPServer(args.id, args.host, args.port)
    server.listen()
