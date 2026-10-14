package main

import (
	"flag"
	"fmt"
	"log"
	"os"

	"github.com/mabbasi001/autonomous-sre/agent/internal/config"
)

var version = "0.1.0-dev" // overridden at build time via -ldflags

func main() {
	showVersion := flag.Bool("version", false, "print version and exit")
	configPath := flag.String("config", "/etc/autonomous-sre/agent.yaml", "path to agent config")
	flag.Parse()

	if *showVersion {
		fmt.Println(version)
		os.Exit(0)
	}

	cfg, err := config.Load(*configPath)
	if err != nil {
		log.Fatalf("load config: %v", err)
	}
	log.Printf("autonomous-sre agent %s starting (environment=%s)", version, cfg.Environment)
}
