package main

import (
	"fmt"
	"net"
	"os"
	"strconv"
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

	defer c.Close()
	counter := 0
	for {

		time.Sleep(60 * time.Second)
		now := time.Now()
		nanos := strconv.FormatInt(now.UnixNano(), 10)
		data := []byte(nanos)
		_, err = c.Write(data)
		sendTime := time.Now().UnixNano()
		fmt.Printf("%s,", strconv.FormatInt(sendTime, 10))
		counter++
		if counter == 121 {
			return
		}
		if err != nil {
			fmt.Println(err)
			return
		}

		buffer := make([]byte, 1024)
		n, _, err := c.ReadFromUDP(buffer)
		recTime := time.Now()
		recNanos := strconv.FormatInt(recTime.UnixNano(), 10)
		if err != nil {
			fmt.Println(err)
			return
		}
		fmt.Printf("%s,", string(buffer[0:n]))
		fmt.Printf("%s,\n", recNanos)
	}
}
