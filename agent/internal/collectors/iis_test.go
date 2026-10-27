package collectors

import (
	"errors"
	"testing"
)

var errFake = errors.New("fake failure")

const appcmdOutput = `APPPOOL "DefaultAppPool" (MgdVersion:v4.0,MgdMode:Integrated,state:Started)
APPPOOL "SitePool" (MgdVersion:v4.0,MgdMode:Integrated,state:Stopped)
`

func TestIISParsesPoolState(t *testing.T) {
	c := &IIS{
		AppPools: []string{"DefaultAppPool", "SitePool"},
		Run:      func(string, ...string) ([]byte, error) { return []byte(appcmdOutput), nil },
	}
	records := c.Collect()
	byPool := map[string]string{}
	for _, r := range records {
		p := r.Data["payload"].(map[string]any)
		byPool[p["pool"].(string)] = p["active_state"].(string)
		if r.Data["type"] != "iis.app_pool" {
			t.Errorf("type = %v", r.Data["type"])
		}
	}
	if byPool["DefaultAppPool"] != "active" {
		t.Errorf("DefaultAppPool = %v", byPool["DefaultAppPool"])
	}
	if byPool["SitePool"] != "inactive" {
		t.Errorf("SitePool = %v", byPool["SitePool"])
	}
}

func TestIISDecodesUTF16Output(t *testing.T) {
	// appcmd emits UTF-16LE with a BOM when redirected
	raw := []byte{0xFF, 0xFE}
	for _, r := range appcmdOutput {
		raw = append(raw, byte(r), byte(r>>8))
	}
	c := &IIS{
		AppPools: []string{"DefaultAppPool"},
		Run:      func(string, ...string) ([]byte, error) { return raw, nil },
	}
	payload := c.Collect()[0].Data["payload"].(map[string]any)
	if payload["active_state"] != "active" {
		t.Errorf("UTF-16 output not decoded: %v", payload)
	}
}

func TestIISNoPoolsNoRecords(t *testing.T) {
	called := false
	c := &IIS{Run: func(string, ...string) ([]byte, error) { called = true; return nil, nil }}
	if records := c.Collect(); len(records) != 0 || called {
		t.Error("unconfigured IIS collector must not query or emit")
	}
}
