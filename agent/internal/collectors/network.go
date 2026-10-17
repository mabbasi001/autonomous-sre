package collectors

import "net"

type Network struct{}

func (Network) Collect() []Record {
	interfaces, err := net.Interfaces()
	if err != nil {
		return nil
	}
	var records []Record
	for _, iface := range interfaces {
		if iface.Flags&net.FlagLoopback != 0 {
			continue
		}
		up := 0.0
		if iface.Flags&net.FlagUp != 0 {
			up = 1.0
		}
		records = append(records,
			metric("host.interface_up", up, map[string]string{"interface": iface.Name}))
	}
	return records
}
