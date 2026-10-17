package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"time"

	"github.com/mabbasi001/autonomous-sre/agent/internal/collectors"
	"github.com/mabbasi001/autonomous-sre/agent/internal/config"
	"github.com/mabbasi001/autonomous-sre/agent/internal/enrollment"
	"github.com/mabbasi001/autonomous-sre/agent/internal/runner"
	"github.com/mabbasi001/autonomous-sre/agent/internal/spool"
	"github.com/mabbasi001/autonomous-sre/agent/internal/transport"
)

var version = "0.1.0-dev" // overridden at build time via -ldflags

const (
	heartbeatInterval  = 30 * time.Second
	configPollInterval = 5 * time.Minute
	spoolMaxBytes      = 10 << 20
)

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

	queue, err := spool.Open(filepath.Join(cfg.StateDir, "spool"), spoolMaxBytes)
	if err != nil {
		log.Fatalf("open spool: %v", err)
	}

	log.Printf("autonomous-sre agent %s starting (environment=%s, agent_id=%s)",
		version, cfg.Environment, creds.AgentID)

	go heartbeatLoop(client)

	remote, remoteVersion := fetchRemoteConfig(client, -1, config.Remote{CollectIntervalSeconds: 60})
	run := &runner.Runner{Client: client, Spool: queue, Collectors: buildCollectors(remote)}
	lastPoll := time.Now()

	for {
		run.Cycle()
		time.Sleep(time.Duration(remote.CollectIntervalSeconds) * time.Second)

		if time.Since(lastPoll) >= configPollInterval {
			lastPoll = time.Now()
			var newVersion int
			remote, newVersion = fetchRemoteConfig(client, remoteVersion, remote)
			if newVersion != remoteVersion {
				remoteVersion = newVersion
				run.Collectors = buildCollectors(remote)
				log.Printf("applied config version %d", remoteVersion)
			}
		}
	}
}

func buildCollectors(remote config.Remote) []collectors.Collector {
	list := []collectors.Collector{&collectors.Host{}, collectors.Network{}}
	if len(remote.Services) > 0 {
		list = append(list, &collectors.Systemd{Units: remote.Services})
	}
	if len(remote.HTTPChecks) > 0 {
		var checks []collectors.HTTPCheck
		for _, check := range remote.HTTPChecks {
			checks = append(checks, collectors.HTTPCheck{
				Name:    check.Name,
				URL:     check.URL,
				Timeout: time.Duration(check.TimeoutSeconds) * time.Second,
			})
		}
		list = append(list, &collectors.HTTPChecker{Checks: checks})
	}
	if len(remote.LogUnits) > 0 {
		var units []collectors.LogUnit
		for _, unit := range remote.LogUnits {
			units = append(units, collectors.LogUnit{Unit: unit.Unit, MaxLines: unit.MaxLines})
		}
		list = append(list, &collectors.Logs{Units: units})
	}
	return list
}

func fetchRemoteConfig(client *transport.Client, currentVersion int, current config.Remote) (config.Remote, int) {
	resp, err := client.Get("/v1/agents/config")
	if err != nil {
		log.Printf("fetch config: %v", err)
		return current, currentVersion
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		log.Printf("fetch config rejected: %s", resp.Status)
		return current, currentVersion
	}

	var envelope struct {
		Version int             `json:"version"`
		Config  json.RawMessage `json:"config"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&envelope); err != nil {
		log.Printf("decode config: %v", err)
		return current, currentVersion
	}
	remote, err := config.ParseRemote(envelope.Config)
	if err != nil {
		log.Printf("parse config: %v", err)
		return current, currentVersion
	}
	return remote, envelope.Version
}

func heartbeatLoop(client *transport.Client) {
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
