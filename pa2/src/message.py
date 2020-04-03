# Message format and types
from enum import IntEnum, unique
import json

@unique
class MessageType(IntEnum):
    UNKNOWN = 0
    CLIENT_REQUEST = 1
    MULTICAST_RAW = 2
    MULTICAST_SEQUENCED = 3
    SERVER_NACK = 4
    SERVER_NACK_REPLY = 5
    SERVER_CLIENT_REPLY = 6
    GROUP_SYNC = 7
    GROUP_SYNC_ACK = 8
    GROUP_QUEUE_TX = 9
    GROUP_TRANSITION = 10
    GROUP_TRANSITION_ACK = 11
    GROUP_STABLE_TRANSITION_REQUEST = 12
    GROUP_STABLE_TRANSITION = 13
    GROUP_NACK_COMPLETE = 14
    PARTITION_DETECTED = 15
    PARTITION_RESOLVED= 16
    REQUEST_QUEUE_STATE = 17
    REQUEST_QUEUE_STATE_ACK = 18
    UPDATE_QUEUE_STATE = 19
    UPDATE_QUEUE_STATE_ACK = 20


class Message:
    def __init__(self,
                 mid: int = -1,
                 data = None,
                 sender=(),
                 gsid=None,
                 sender_id=None,
                 sender_type=None,
                 message_type=MessageType.UNKNOWN,
                 error=None,
                 config_id=None
                 ):
        self.gsid = gsid
        self.mid = mid
        self.data = data
        self.message_type = message_type
        self.sender_id = sender_id
        self.config_id = config_id
        # can be 'client' or 'server'
        self.sender_type = sender_type
        self.sender = sender
        self.error = error

    def to_string(self):
        return json.dumps({
            'mid': self.mid,
            'data': self.data,
            'sender': self.sender,
            'gsid': self.gsid,
            'sender_id': self.sender_id,
            'sender_type': self.sender_type,
            'message_type': self.message_type,
            'error': self.error,
            'config_id': self.config_id,
        })

    @classmethod
    def from_string(cls, data):
        """Creates a new message object initialized with data
        """
        payload = json.loads(data)
        return Message(
            mid=payload['mid'],
            data=payload['data'],
            sender=payload['sender'],
            gsid=payload['gsid'],
            sender_id=payload['sender_id'],
            sender_type=payload['sender_type'],
            message_type=payload['message_type'],
            error=payload['error'],
            config_id=payload['config_id'],
        )

    def has_gsid(self):
        if self.gsid == None:
            return False
        return True
