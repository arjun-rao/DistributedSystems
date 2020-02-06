package main

import (
	"fmt"
	"net"
	"os"
	"strconv"
	"time"
)

func handleConnection(connection *net.UDPConn) {

	// Read message from UDP socket
	buffer := make([]byte, 1024)
	n, addr, err := connection.ReadFromUDP(buffer)
	if err != nil {
		fmt.Println(err)
		return
	}
	// Print received message
	if tReceive, err := strconv.ParseInt(string(buffer[0:n-1]), 10, 64); err == nil {
		fmt.Printf("Request Receive Time: %s\n", time.Unix(0, tReceive).String())
	}

	tServer := time.Now().UnixNano()
	data := []byte(strconv.FormatInt(tServer, 10))
	_, err = connection.WriteToUDP(data, addr)
	if err != nil {
		fmt.Println(err)
		return
	}
	fmt.Printf("Send Time: %s\n", time.Unix(0, tServer).String())
}

func main() {
	arguments := os.Args
	if len(arguments) == 1 {
		fmt.Println("Please provide a port number!")
		return
	}

	PORT := ":" + arguments[1]

	fmt.Printf("Listening on port %s\n", PORT)

	s, err := net.ResolveUDPAddr("udp4", PORT)
	if err != nil {
		fmt.Println(err)
		return
	}

	connection, err := net.ListenUDP("udp4", s)
	if err != nil {
		fmt.Println(err)
		return
	}

	defer connection.Close()

	for {
		handleConnection(connection)
	}
}
