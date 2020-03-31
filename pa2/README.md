## Programming Assignment 2

## Authors: Aditi Prakash (adpr5166), Arjun Rao (arra8056)

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


## How to run

1) Decide on number of servers N
2) Start the N servers on different ports using the following command:

    ```
    # SID starts from 1 and increments for each additional server. N is the total number of servers
    python server.py --port 9003 --id <SID> --n <N>
    ```
3) Start the client

    ```
    python client.py
    ```
    Type 'help' at the prompt to see instructions for how to use the client.

## Phase Two

In this phase, we handle recovery from server failures and network partitions. 

A group communication protocol is established in the network. 

Recovery from server failures:
* The group configuration moves to a transitive configuration when one or more servers fail from the existing group causing a new group confiuration to be formed.
* The transitive configuration assures consistency of data amongst the different servers.
* The servers in the transitive configuration reach stable state when all of their global squence numbers match.
* Once a stable state is reached, the new group configuration is set up.
* For servers that recover from failure, a new configuration is set up.

Recovery from network partitions:
* Incase of a network partition, new configurations are established at both ends of the partition.
* The two groups exist individually, and process requests separately.
* As per CAP theorem, in the event of a network partition, a distributed system can provide either consistency or availability, but not both. In our case, we prioritize Consistency over Availability. 
* One of the paritions become the primary partition(we picked the partition that has the server with the highests server-id to be the primary partition), while the other partition(s) serve as the secondary partition(s). When the partition merges, the primary partition is used as a reference for all secondary partitions. The secondary partitions remove their current state and replace with data from the primary partition. 

## Current Status

### What works:

* All functionalities expected from Phase 2 works.


## References
* UDP Client-Server Python - [link](https://tutorialedge.net/python/udp-client-server-python/)
* Multicast - [link](https://stackoverflow.com/questions/603852/how-do-you-udp-multicast-in-python)
    * `sudo route add -net 224.0.0.0/5 127.0.0.1`
    * `sudo route add -net 232.0.0.0/5 192.168.1.3`
