# message class
import json

class Message:
    def __init__(self,mid,data,sender,gsid=None):
        self.gs_id = gsid
        self.m_id = mid
        self.data = data
        self.sender = sender

    def to_string(self):
        return json.dumps({
            'mid': self.m_id,
            'gsid': self.gs_id,
            'sender': self.sender,
            'data': self.data
        })

    @classmethod
    def from_string(cls, data):
        payload = json.loads(data)
        return Message(payload['mid'], payload['data'], payload['sender'], payload['gsid'])

    def has_gsid(self):
        if self.gs_id == None:
            return False
        return True