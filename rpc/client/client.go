// Package grpctimer implements a client for GRPC service.
package main

import (
	"context"
	"fmt"
	"log"
	"os"
	"time"

	pb "ds/rpc/grpctimer"

	"google.golang.org/grpc"
)

func main() {
	// Contact the server and print out its response.
	arguments := os.Args
	if len(arguments) == 1 {
		fmt.Println("Please provide hostname:port")
		return
	}
	address := "localhost:50051"
	if len(os.Args) > 1 {
		address = os.Args[1]
	}
	// Set up a connection to the server.
	conn, err := grpc.Dial(address, grpc.WithInsecure(), grpc.WithBlock())
	if err != nil {
		log.Fatalf("did not connect: %v", err)
	}
	defer conn.Close()
	c := pb.NewGrpcTimeClient(conn)

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Hour)
	defer cancel()
	counter := 1
	for {

		time.Sleep(60 * time.Second)
		r, err := c.SendTime(ctx, &pb.GrpcTimeRequest{Data: time.Now().UnixNano()})
		sendTime := time.Now().UnixNano()
		if err != nil {
			log.Fatalf("could not fetch time: %v", err)
		}
		fmt.Printf("%d,", sendTime)
		serverTime := r.GetData()
		recTime := time.Now().UnixNano()
		fmt.Printf("%d,", serverTime)
		fmt.Printf("%d,\n", recTime)
		counter++
		if counter == 121 {
			return
		}
	}
}
