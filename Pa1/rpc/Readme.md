# GRPC client and server

## Notes:
* Relative imports requires that folder containing the rpc directory be named `ds`.
* It must to be present in your Go Path (example: `~/go/src/ds`).
* Install (protoc)[https://github.com/protocolbuffers/protobuf/releases] compiler (for generating the go code from the proto file)
* Install the go protobuff plugin - `go get -u github.com/golang/protobuf/protoc-gen-go`
* Install grpc for go `go get -u google.golang.org/grpc`


# Compile protobuf

Run in the rpc directory (ds/rpc)
```
protoc -I grpctimer grpctimer/grpctimer.proto --go_out=plugins=grpc:grpctimer
```

## Compile Client & Server

The following commands can be used to compile the client and server programs - paths can be modified as desired.
```
mkdir out
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


