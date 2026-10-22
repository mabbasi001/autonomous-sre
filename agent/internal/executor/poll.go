package executor

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"

	"github.com/mabbasi001/autonomous-sre/agent/internal/transport"
)

// Poll fetches pending commands, acknowledges, executes and reports each.
func Poll(client *transport.Client, e *Executor) error {
	resp, err := client.Get("/v1/agents/commands")
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("fetch commands: %s", resp.Status)
	}

	var envelope struct {
		Commands []Command `json:"commands"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&envelope); err != nil {
		return err
	}

	for _, cmd := range envelope.Commands {
		ackResp, err := client.Post("/v1/agents/commands/"+cmd.ID+"/ack", map[string]any{})
		if err != nil {
			return err
		}
		ackResp.Body.Close()
		if ackResp.StatusCode != http.StatusOK {
			log.Printf("command %s ack rejected: %s", cmd.ID, ackResp.Status)
			continue
		}

		result := e.Handle(cmd)
		resultResp, err := client.Post("/v1/agents/commands/"+cmd.ID+"/result", result)
		if err != nil {
			log.Printf("command %s result delivery failed: %v", cmd.ID, err)
			continue
		}
		resultResp.Body.Close()
		if resultResp.StatusCode != http.StatusOK {
			log.Printf("command %s result rejected: %s", cmd.ID, resultResp.Status)
		}
	}
	return nil
}
