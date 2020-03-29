from enum import IntEnum, unique
import json
from multiprocessing import Manager

@unique
class ConfigStage(IntEnum):
    INIT = 0
    WAIT_FOR_ACK = 1
    WAIT_FOR_TRANSITION = 2
    STABLE = 3

class Config:
    def __init__(self, sync_manager, server_id):
        self.manager = sync_manager
        self.member_count = self.manager.Value('i', 0)
        self.view_server = self.manager.dict()
        self.server_view = self.manager.dict()
        # server data is of the form {addr: (HOST, PORT), gsid: int}
        self.server_data = self.manager.dict()
        self.view_id = self.manager.Value('i', -1)
        self.server_id = self.manager.Value('i', server_id)


    def get_addr_from_view_id(self,view_id):
        return self.server_data[self.view_server[view_id]]['addr']

    def get_view_from_server_id(self,server_id):
        return self.view_server[server_id]

    def get_server_from_view(self,view_id):
        return self.server_view[view_id]

    def add_member(self, server_id, unicast_addr, gsid, view_id):
        self.member_count.set(self.member_count.get() + 1)
        self.server_view[server_id] = view_id
        self.view_server[view_id] = server_id
        self.add_server(server_id, unicast_addr, gsid)
        return view_id

    def reset_view_ids(self):
        self.view_id.set(-1)
        self.member_count.set(0)
        self.view_server = self.manager.dict()
        self.server_view = self.manager.dict()

    def add_server(self, server_id, unicast_addr, gsid):
        self.server_data[server_id] = {'addr': unicast_addr, 'gsid': gsid}

    def reset_gsid(self):
        self.server_data = self.manager.dict()

    def get_max_gsid(self):
        max_gsid = -1
        for key in self.server_data:
            if self.server_data[key]['gsid'] > max_gsid:
                max_gsid = self.server_data[key]['gsid']
        return max_gsid

    def compute_view_id(self):
        """Returns calculated view id
        """
        view_id = sorted(self.server_data.keys()).index(self.server_id.get())
        return view_id

    def can_transition(self):
        transition_flag = True
        for key in self.server_data:
            if self.server_data[key]['gsid'] != self.get_max_gsid():
                transition_flag = False
                break
        return transition_flag

    def can_transition_to_stable(self):
        expected_count = self.member_count.get()
        for key in self.server_data:
            if 'member_count' not in self.server_data[key]:
                return False
            if self.server_data[key]['member_count'] != expected_count:
                return False
        return True

    def is_leader(self):
        if self.server_id.get() ==  max(self.server_data):
            return True
        return False

    def get_responsible_server(self, msg):
        """Returns the View ID of the responsible server for this message"""
        return (msg.m_id % self.member_count.get())

    def is_responsible_server(self, msg):
        """Returns true if this server is responsible for msg"""
        if (msg.mid % self.member_count.get()) == self.view_id.get():
            return True
        return False

