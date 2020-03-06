# DistributedSystems Programming Assignment 1

Code for CSCI 5673 - Programming Assignment 1

## Authors: Arjun Ramesh Rao, Aditi Prakash

## Notes:
* Relative imports requires that project root directory be named `ds`.
* Project root must to be present in your Go Path (example: `~/go/src/ds`).
* Install (protoc)[https://github.com/protocolbuffers/protobuf/releases] compiler (for generating the go code from the proto file)
* Install the go protobuff plugin - `go get -u github.com/golang/protobuf/protoc-gen-go`
* Install grpc for go `go get -u google.golang.org/grpc`


# Compile proto file for generating protobuffers code in go

Run in the rpc directory (ds/rpc)
```
cd rpc
protoc -I grpctimer grpctimer/grpctimer.proto --go_out=plugins=grpc:grpctimer
```

## Makefile instructions (After compiling proto file)

* Run `make deps` to install dependencies
* Run `make all` to build all binaries for udp and rpc (built binaries can be found in the `out` sub-directory in respective udp/rpc directories)
* Run `make clean` to remove all binaries
