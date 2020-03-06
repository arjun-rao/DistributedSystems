from collections import defaultdict
class FTQueue:
    def __init__(self):
        self.data = defaultdict(list)

    def qCreate(self, label: int) -> int:
        if label not in self.data.keys():
            self.data[label] = list()
        else:
            return label

    def qDestroy(self,queue_id: int):
        del self.data[queue_id]
        return queue_id

    def qId(self, label: int) -> int:
        if label in self.data:
            return label
        return -1

    def qPush(self, queue_id: int, item: int):
        self.data[queue_id].append(item)
        pass

    def qPop(self,queue_id: int) -> int:
        return self.data[queue_id].pop()

    def qTop(self, queue_id: int) -> int:
        return self.data[queue_id][0]

    def qSize(self, queue_id: int) -> int:
        return len(self.data[queue_id])

    def qDisplay(self):
        print(self.data)
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


