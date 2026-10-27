//go:build !windows

package main

func isWindowsService() bool { return false }

func runService(string, func(stop <-chan struct{})) error { return nil }
