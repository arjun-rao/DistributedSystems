from enum import IntEnum, unique
import json
from multiprocessing import Manager

@unique
class ConfigStage(IntEnum):
    INIT = 0
    WAIT_FOR_ACK = 1
    WAIT_FOR_TRANSITION = 2
    STABLE = 3
    UNKOWN = 4
    WAIT_FOR_NACK = 5

class Config:
    def __init__(self, sync_manager, lock, server_id):
        self.manager = sync_manager
        self.lock = lock
        with self.lock:
            self.member_count = self.manager.Value('i', 0)
            self._config_gen_id = self.manager.Value('i', -1)
            self.config_id = self.manager.Value('s', '')
            self.view_server = self.manager.dict()
            self.server_view = self.manager.dict()
            # server data is of the form {addr: (HOST, PORT), gsid: int}
            self.server_data = self.manager.dict()
            self.view_id = self.manager.Value('i', -1)
            self.server_id = self.manager.Value('i', server_id)

    def generate_config_id(self):
        with self.lock:
            old_id = self._config_gen_id.get()
            self._config_gen_id.set(old_id + 1)
            new_id = '{}-conf-{}'.format(self.server_id.get(), old_id + 1)
            return new_id

    def get_addr_from_view_id(self,view_id):
        return self.server_data[self.view_server[view_id]]['addr']

    def get_view_from_server_id(self,server_id):
        return self.view_server[server_id]

    def get_server_from_view(self,view_id):
        return self.server_view[view_id]

    def add_member(self, server_id, unicast_addr, gsid, view_id):
        with self.lock:
            if server_id not in self.server_view.keys():
                self.member_count.set(self.member_count.get() + 1)
                self.server_view[server_id] = view_id
                self.view_server[view_id] = server_id
        self.add_server(server_id, unicast_addr, gsid)
        return view_id

    def reset_view_ids(self):
        with self.lock:
            self.view_id.set(-1)
            self.member_count.set(0)
            for key in self.view_server.keys():
                del self.view_server[key]
            for key in self.server_view.keys():
                del self.server_view[key]

    def add_server(self, server_id, unicast_addr, gsid):
        with self.lock:
            self.server_data[server_id] = {'addr': unicast_addr, 'gsid': gsid}

    def reset_gsid(self):
        with self.lock:
            for key in self.server_data.keys():
                del self.server_data[key]

    def get_max_gsid(self):
        max_gsid = -1
        min_gsid = 999999
        min_gsid_key = -1
        for key in self.server_data.keys():
            if self.server_data[key]['gsid'] > max_gsid:
                max_gsid = self.server_data[key]['gsid']
            if self.server_data[key]['gsid'] < min_gsid:
                min_gsid = self.server_data[key]['gsid']
                min_gsid_key = key
        return max_gsid, (min_gsid_key, min_gsid)

    def compute_view_id(self):
        """Returns calculated view id
        """
        view_id = sorted(self.server_data.keys()).index(self.server_id.get())
        return view_id

    def can_transition(self):
        transition_flag = True
        max_gsid, _ = self.get_max_gsid()
        for key in self.server_data.keys():
            if self.server_data[key]['gsid'] != max_gsid:
                transition_flag = False
                break
        return transition_flag

    def can_transition_to_stable(self):
        with self.lock:
            expected_count = self.member_count.get()
            for key in self.server_data.keys():
                if 'member_count' not in self.server_data[key]:
                    return False
                if self.server_data[key]['member_count'] != expected_count:
                    return False
            return True

    def is_leader(self):
        if self.server_id.get() ==  max(self.server_data.keys()):
            return True
        return False

    def get_responsible_server(self, msg):
        """Returns the View ID of the responsible server for this message"""
        return (msg.mid % self.member_count.get())

    def is_responsible_server(self, msg):
        """Returns true if this server is responsible for msg"""
        if (msg.mid % self.member_count.get()) == self.view_id.get():
            return True
        return False

