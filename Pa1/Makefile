# Go parameters
GOCMD=go
GOGET=$(GOCMD) get -u
GOBUILD=$(GOCMD) build
SERVER_BINARY_NAME=server
CLIENT_BINARY_NAME=client

SERVER_BINARY_UDP=$(SERVER_BINARY_NAME)_udp
SERVER_BINARY_RPC=$(SERVER_BINARY_NAME)_rpc
CLIENT_BINARY_UDP=$(CLIENT_BINARY_NAME)_udp
CLIENT_BINARY_RPC=$(CLIENT_BINARY_NAME)_rpc


all: clean build
build:
		mkdir -p  udp/out
		$(GOBUILD) -v -o udp/out/$(SERVER_BINARY_UDP) udp/server.go
		$(GOBUILD) -v -o udp/out/$(CLIENT_BINARY_UDP) udp/client.go
		mkdir -p  rpc/out
		$(GOBUILD) -v -o rpc/out/$(SERVER_BINARY_RPC) rpc/server/server.go
		$(GOBUILD) -v -o rpc/out/$(CLIENT_BINARY_RPC) rpc/client/client.go

clean:
		rm -f udp/out/$(SERVER_BINARY_UDP)
		rm -f udp/out/$(CLIENT_BINARY_UDP)
		rm -f rpc/out/$(SERVER_BINARY_RPC)
		rm -f rpc/out/$(CLIENT_BINARY_RPC)

deps:
		$(GOGET) google.golang.org/grpc
		$(GOGET) github.com/golang/protobuf/protoc-gen-go
