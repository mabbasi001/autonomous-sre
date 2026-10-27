//go:build windows

package main

import "golang.org/x/sys/windows/svc"

type agentService struct {
	run func(stop <-chan struct{})
}

func (s *agentService) Execute(
	_ []string, requests <-chan svc.ChangeRequest, status chan<- svc.Status,
) (bool, uint32) {
	status <- svc.Status{State: svc.StartPending}
	stop := make(chan struct{})
	done := make(chan struct{})
	go func() {
		s.run(stop)
		close(done)
	}()
	status <- svc.Status{State: svc.Running, Accepts: svc.AcceptStop | svc.AcceptShutdown}

	for {
		select {
		case req := <-requests:
			switch req.Cmd {
			case svc.Interrogate:
				status <- req.CurrentStatus
			case svc.Stop, svc.Shutdown:
				status <- svc.Status{State: svc.StopPending}
				close(stop)
				<-done
				return false, 0
			}
		case <-done:
			return false, 0
		}
	}
}

func isWindowsService() bool {
	ok, err := svc.IsWindowsService()
	return err == nil && ok
}

func runService(name string, run func(stop <-chan struct{})) error {
	return svc.Run(name, &agentService{run: run})
}
