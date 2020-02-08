# GRPC client and server

Note: This requires the repository to be present in your Go Path (example: `~/go/`).

If your go path is `/home/user/go/`, then clone the repository using
```
git clone https://github.com/arjun-rao/DistributedSystems.git ~/go/src/ds
```

or if you have already cloned it somewhere, create a symlink to the repo in your go path:
```
ln -s <path_to_some_dir>/DistributedSystems ~/go/src/ds
```

# Compile protobuf

Run in the rpc directory (DistributedSystems/rpc)
```
protoc -I grpctimer grpctimer/grpctimer.proto --go_out=plugins=grpc:grpctimer
```

## Compile Client & Server

Make a directory called out in the rpc directory.

```
cd out
go build -o client ../client/client.go
go build -o server ../server/server.go
```

## Run client and server in two different terminals/machines

Provide port for server (Example: 9000)
```
./server 9000
```

Connect to server via client - provide hostname:port as argument:
```
./client 127.0.0.1:9000
```


