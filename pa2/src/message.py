# message class
class Message:
    def __init__(self,mid,data,sender,gsid=None):
        self.gs_id = gsid
        self.m_id = mid
        self.data = data
        self.sender = sender

    def has_gsid(self):
        if self.gs_id == None:
            return False
        return True