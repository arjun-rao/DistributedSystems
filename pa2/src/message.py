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
    SERVER_JOIN = 7
    SERVER_JOIN_ACK = 8

class Message:
    def __init__(self,
                 mid: int,
                 data: str,
                 sender=(),
                 gsid=None,
                 sender_id=None,
                 sender_type=None,
                 message_type=MessageType.UNKNOWN,
                 error=None
                 ):
        self.gs_id = gsid
        self.m_id = mid
        self.data = data
        self.message_type = message_type
        self.sender_id = sender_id
        # can be 'client' or 'server'
        self.sender_type = sender_type
        self.sender = sender
        self.error = error

    def to_string(self):
        return json.dumps({
            'mid': self.m_id,
            'data': self.data,
            'sender': self.sender,
            'gsid': self.gs_id,
            'sender_id': self.sender_id,
            'sender_type': self.sender_type,
            'message_type': self.message_type,
            'error': self.error,
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
        )

    def has_gsid(self):
        if self.gs_id == None:
            return False
        return True
