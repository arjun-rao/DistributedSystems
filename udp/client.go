package main

import (
	"fmt"
	"net"
	"os"
	"strconv"
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

		time.Sleep(60 * time.Second)
		now := time.Now()
		nanos := strconv.FormatInt(now.UnixNano(), 10)
		data := []byte(nanos)
		fmt.Printf("%s,", data)
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
		rec_time := time.Now()
		rec_nanos := strconv.FormatInt(rec_time.UnixNano(), 10)
		if err != nil {
			fmt.Println(err)
			return
		}
		fmt.Printf("%s,", string(buffer[0:n]))
		fmt.Printf("%s,\n", rec_nanos)
	}
}
