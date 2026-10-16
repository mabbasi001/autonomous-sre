package main

import (
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"time"

	"github.com/mabbasi001/autonomous-sre/agent/internal/config"
	"github.com/mabbasi001/autonomous-sre/agent/internal/enrollment"
	"github.com/mabbasi001/autonomous-sre/agent/internal/transport"
)

var version = "0.1.0-dev" // overridden at build time via -ldflags

const heartbeatInterval = 30 * time.Second

func main() {
	showVersion := flag.Bool("version", false, "print version and exit")
	configPath := flag.String("config", "/etc/autonomous-sre/agent.yaml", "path to agent config")
	enrollToken := flag.String("enroll", "", "one-time enrollment token")
	flag.Parse()

	if *showVersion {
		fmt.Println(version)
		os.Exit(0)
	}

	cfg, err := config.Load(*configPath)
	if err != nil {
		log.Fatalf("load config: %v", err)
	}

	if *enrollToken != "" {
		hostname, err := os.Hostname()
		if err != nil {
			log.Fatalf("resolve hostname: %v", err)
		}
		creds, err := enrollment.Enroll(cfg.ControlPlaneURL, *enrollToken, hostname, cfg.Environment)
		if err != nil {
			log.Fatalf("enroll: %v", err)
		}
		if err := enrollment.Save(cfg.StateDir, creds); err != nil {
			log.Fatalf("save credentials: %v", err)
		}
		log.Printf("enrolled as agent %s", creds.AgentID)
	}

	creds, err := enrollment.Load(cfg.StateDir)
	if err != nil {
		log.Fatalf("no credentials in %s: run with -enroll <token> first", cfg.StateDir)
	}

	client := &transport.Client{
		BaseURL: cfg.ControlPlaneURL,
		AgentID: creds.AgentID,
		Secret:  creds.Secret,
	}

	log.Printf("autonomous-sre agent %s starting (environment=%s, agent_id=%s)",
		version, cfg.Environment, creds.AgentID)

	for {
		beat(client)
		time.Sleep(heartbeatInterval)
	}
}

func beat(client *transport.Client) {
	resp, err := client.Post("/v1/agents/heartbeat", map[string]string{"version": version})
	if err != nil {
		log.Printf("heartbeat failed: %v", err)
		return
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		log.Printf("heartbeat rejected: %s", resp.Status)
	}
}
