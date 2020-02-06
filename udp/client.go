package main

import (
	"fmt"
	"net"
	"os"
	"strings"
	"time"
)

func main() {
	arguments := os.Args
	if len(arguments) == 1 {
		fmt.Println("Please provide a host:port string")
		return
	}
	CONNECT := arguments[1]

	s, err := net.ResolveUDPAddr("udp4", CONNECT)
	c, err := net.DialUDP("udp4", nil, s)
	if err != nil {
		fmt.Println(err)
		return
	}

	fmt.Printf("The UDP server is %s\n", c.RemoteAddr().String())
	defer c.Close()

	for {
		// reader := bufio.NewReader(os.Stdin)
		// fmt.Print(">> ")
		// text, _ := reader.ReadString('\n')
		// data := []byte(text + "\n")
		data := []byte(time.Now().UTC().String())
		fmt.Printf("Client message Sent at time: %s\n", data)
		_, err = c.Write(data)
		if strings.TrimSpace(string(data)) == "STOP" {
			fmt.Println("Exiting UDP client!")
			return
		}

		if err != nil {
			fmt.Println(err)
			return
		}

		buffer := make([]byte, 1024)
		n, _, err := c.ReadFromUDP(buffer)
		rec_time := []byte(time.Now().UTC().String())
		if err != nil {
			fmt.Println(err)
			return
		}
		fmt.Printf("Reply: %s\n", string(buffer[0:n]))
		fmt.Printf("Response received at time: %s\n", rec_time)
	}
}
