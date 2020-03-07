from collections import defaultdict
from enum import IntEnum, unique

# Error codes for queue errors
@unique
class QueueErrors(IntEnum):
    UNKNOWN = -1
    QUEUE_NOT_FOUND = -2
    QUEUE_EMPTY = -3


class FTQueue:
    def __init__(self, sync_manager):
        self.manager = sync_manager
        self.data =  self.manager.dict()

    def qCreate(self, label: int) -> int:
        if label not in self.data.keys():
            self.data[label] = self.manager.list()
        return label, None

    def qId(self, label: int) -> int:
        if label in self.data:
            return label, None
        return -1, QueueErrors.QUEUE_NOT_FOUND

    def qDestroy(self,queue_id: int):
        if self.qId(queue_id) != -1:
            del self.data[queue_id]
            return queue_id, None
        else:
            return None, QueueErrors.QUEUE_NOT_FOUND

    def qPush(self, queue_id: int, item: int):
        if self.qId(queue_id)[0] == -1:
            self.qCreate(queue_id)
        self.data[queue_id].append(item)
        return None, None

    def qPop(self,queue_id: int) -> int:
        if self.qId(queue_id)[0] != -1:
            if self.qSize(queue_id) > 0:
                return self.data[queue_id].pop(0), None
            return None, QueueErrors.QUEUE_EMPTY
        return None, QueueErrors.QUEUE_NOT_FOUND

    def qTop(self, queue_id: int) -> int:
        if self.qId(queue_id)[0] != -1:
            if self.qSize(queue_id) > 0:
                return self.data[queue_id][0], None
            return None, QueueErrors.QUEUE_EMPTY
        return None, QueueErrors.QUEUE_NOT_FOUND

    def qSize(self, queue_id: int) -> int:
        if self.qId(queue_id)[0] != -1:
            return len(self.data[queue_id]), None
        return None, QueueErrors.QUEUE_NOT_FOUND

    def qDisplay(self):
        for item, value in self.data.items():
            print(item, [x for x in value])
        return


if __name__ == "__main__":
    q = FTQueue()
    print("--Creating queue--")
    q.qCreate(1)
    q.qDisplay()
    print("--Add elements to queue--")
    q.qPush(1,3)
    q.qPush(1,5)
    q.qDisplay()
    print("--Add qid--")
    q.qCreate(2)
    q.qDisplay()
    print("--Delete q--")
    q.qDestroy(2)
    q.qDisplay()
    print("--Search for qid--")
    print(q.qId(2))
    print(q.qId(1))
    print("--Pop--")
    print(q.qPop(1))
    print("--Top--")
    print(q.qTop(1))
    print("--Size--")
    print(q.qSize(1))


