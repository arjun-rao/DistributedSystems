// Package grpctimer implements a server for GRPC service.
package main

import (
	"context"
	"fmt"
	"log"
	"net"
	"os"
	"time"

	pb "ds/rpc/grpctimer"

	"google.golang.org/grpc"
	"google.golang.org/grpc/keepalive"
)

// server is used to implement helloworld.GreeterServer.
type server struct {
	pb.UnimplementedGrpcTimeServer
}

// SayHello implements helloworld.GreeterServer
func (s *server) SendTime(ctx context.Context, in *pb.GrpcTimeRequest) (*pb.GrpcTimeResponse, error) {
	log.Printf("Received: %v", in.GetData())
	return &pb.GrpcTimeResponse{Data: time.Now().UnixNano()}, nil
}

func main() {
	arguments := os.Args
	if len(arguments) == 1 {
		fmt.Println("Please provide a port number!")
		return
	}

	PORT := ":" + arguments[1]

	lis, err := net.Listen("tcp", PORT)
	if err != nil {
		log.Fatalf("failed to listen: %v", err)
	}
	s := grpc.NewServer(
		grpc.KeepaliveParams(keepalive.ServerParameters{
			MaxConnectionIdle: 5 * time.Minute, // <--- This fixes it!
		}),
	)
	pb.RegisterGrpcTimeServer(s, &server{})
	if err := s.Serve(lis); err != nil {
		log.Fatalf("failed to serve: %v", err)
	}
}
