# message class
import json

class Message:
    def __init__(self, mid: int, data: str, sender: list, gsid=None, sender_id=None, sender_type=None):
        self.gs_id = gsid
        self.m_id = mid
        self.data = data
        self.sender_id = sender_id
        # can be 'client' or 'server'
        self.sender_type = sender_type
        self.sender = sender

    def to_string(self):
        return json.dumps({
            'mid': self.m_id,
            'data': self.data,
            'sender': self.sender,
            'gsid': self.gs_id,
            'sender_id': self.sender_id,
            'sender_type': self.sender_type,
        })

    @classmethod
    def from_string(cls, data) -> Message:
        """Creates a new message object initialized with data
        """
        payload = json.loads(data)
        return Message(
            payload['mid'],
            payload['data'],
            payload['sender'],
            payload['gsid'],
            payload['sender_id'],
            payload['sender_type'],
        )

    def has_gsid(self):
        if self.gs_id == None:
            return False
        return True

    def is_responsible(self,server_count: int, self_id: int) -> bool:
        if self.m_id % server_count == self_id:
            return True
        return False

    def server_responsible(self, server_count: int) -> int:
        return self.m_id % server_count
