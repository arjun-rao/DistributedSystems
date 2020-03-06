## Programming Assignment 2

The goal of this assignment is to implement a fault-tolerant queue data structure called `FTQueue` that exports the following operations to the clients:

```
// If there exists a queue associated with label, return the
//corresponding queue id; queue ids are unique positive integers
//Otherwise, create a new queue of integers associated with
//label and return a queue id
int qCreate (int label);
```
```
int qDestroy(int queue_id); //deletes a queue
```
```
// qID returns queue id of the queue associated with label if one exists
//Otherwise, return -1
int qId (int label);
```
```
void qPush (int queue_id, int item); // enters item in the queue
int qPop (int queue_id); // removes an item from the queue and returns it
int qTop (int queue_id); // returns the value of the first element in the queue
int qSize (int queue_id); // returns the number of items in the queue
```
FTQueue is replicated over n servers and must be able to tolerate server crash failures as well as communication omission failure including network partitions.


## Phase One

In this phase, implement FTQueue assuming that there are no server failures or
network partitions. However, the communication system may suffer from omission failures, which means messages may get lost. In particular, use UDP as your underlying communication protocol and negative acknowledgement technique to recover from message losses.

To ensure the consistency of your replicated data structure, implement a group
communication middleware that includes a total order, reliable atomic multicast
protocol as described below:

* To multicast a message, a group member sends that message to every group member.
* Assume that the group members have unique ids, 0 to n-1.
* For each multicast message, one group member sends out a global sequence for that message to all group members. This global sequence number determines the delivery order of that message.
* Global sequence number k is sent out by group member k mod n.
* Group members deliver messages in the order determined by their global sequence numbers


## TODO

- [x] Create a `FTQueue Class` that has methods for queue operations mentioned above that writes queue to file.
- [ ] Create a UDP server that listens for incoming messages for queue operations.
- [ ] Create a UDP client that can send messages to the server to perform queue operations.


## References
* UDP Client-Server Python - [link](https://tutorialedge.net/python/udp-client-server-python/)
* Multicast - [link](https://stackoverflow.com/questions/603852/how-do-you-udp-multicast-in-python)