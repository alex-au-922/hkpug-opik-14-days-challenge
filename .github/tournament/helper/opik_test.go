package helper

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

func TestLoadOpikReplaysDiscoveryBundle(t *testing.T) {
	t.Parallel()

	requests := make([]string, 0)
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		requests = append(requests, request.Method+" "+request.URL.Path)
		if request.Header.Get("Comet-Workspace-Name") != "default" {
			t.Errorf("workspace header = %q", request.Header.Get("Comet-Workspace-Name"))
		}
		writer.WriteHeader(http.StatusNoContent)
	}))
	defer server.Close()

	bundle := t.TempDir()
	writeJSON(t, bundle, "run.json", map[string]any{
		"schema_version":   1,
		"bundle_partition": "discovery",
		"project_name":     "hkpug-team-07-run-1",
		"holdout": map[string]any{
			"case_count": 10,
			"criteria":   map[string]any{"faithfulness": 8.4},
			"score":      82.1,
		},
	})
	writeJSON(t, bundle, "trace_payload.json", map[string]any{
		"traces": []any{map[string]any{"id": "019f0000-0000-7000-8000-000000000001", "metadata": map[string]any{"partition": "discovery"}}},
	})
	writeJSON(t, bundle, "span_payload.json", map[string]any{
		"spans": []any{
			map[string]any{"id": "019f0000-0000-7000-8000-000000000002", "trace_id": "019f0000-0000-7000-8000-000000000001", "metadata": map[string]any{"partition": "discovery"}},
			map[string]any{"id": "019f0000-0000-7000-8000-000000000003", "trace_id": "019f0000-0000-7000-8000-000000000001", "metadata": map[string]any{"partition": "discovery"}},
		},
	})
	writeJSON(t, bundle, "trace_feedback.json", map[string]any{
		"scores": []any{map[string]any{"id": "019f0000-0000-7000-8000-000000000001", "name": "faithfulness", "value": 0.84}},
	})
	writeJSON(t, bundle, "span_feedback.json", map[string]any{
		"scores": []any{map[string]any{"id": "019f0000-0000-7000-8000-000000000002", "name": "faithfulness", "value": 0.84}},
	})

	result, err := LoadOpik(LoadOpikOptions{
		FeedbackDirectory: bundle,
		BaseURL:           server.URL + "/api",
		Workspace:         "default",
		Client:            server.Client(),
	})
	if err != nil {
		t.Fatalf("LoadOpik returned an error: %v", err)
	}
	wantResult := LoadOpikResult{
		ProjectName:        "hkpug-team-07-run-1",
		TraceCount:         1,
		SpanCount:          2,
		TraceFeedbackCount: 1,
		SpanFeedbackCount:  1,
	}
	if result != wantResult {
		t.Fatalf("result = %#v, want %#v", result, wantResult)
	}
	encodedResult, err := json.Marshal(result)
	if err != nil {
		t.Fatal(err)
	}
	wantEncodedResult := `{"project_name":"hkpug-team-07-run-1","trace_count":1,"span_count":2,"trace_feedback_count":1,"span_feedback_count":1}`
	if string(encodedResult) != wantEncodedResult {
		t.Fatalf("encoded result = %s, want %s", encodedResult, wantEncodedResult)
	}
	wantRequests := []string{
		"POST /api/v1/private/traces/batch",
		"POST /api/v1/private/spans/batch",
		"PUT /api/v1/private/traces/feedback-scores",
		"PUT /api/v1/private/spans/feedback-scores",
	}
	if !reflect.DeepEqual(requests, wantRequests) {
		t.Fatalf("requests = %v, want %v", requests, wantRequests)
	}
}

func TestLoadOpikRejectsNonDiscoveryBundles(t *testing.T) {
	t.Parallel()

	bundle := t.TempDir()
	writeJSON(t, bundle, "run.json", map[string]any{
		"schema_version":   1,
		"bundle_partition": "holdout",
		"project_name":     "not-safe",
		"holdout":          map[string]any{"case_count": 1, "criteria": map[string]any{}, "score": 0},
	})
	for name, key := range map[string]string{
		"trace_payload.json":  "traces",
		"span_payload.json":   "spans",
		"trace_feedback.json": "scores",
		"span_feedback.json":  "scores",
	} {
		writeJSON(t, bundle, name, map[string]any{key: []any{}})
	}

	if _, err := LoadOpik(LoadOpikOptions{
		FeedbackDirectory: bundle,
		BaseURL:           "http://localhost:5173/api",
	}); err == nil {
		t.Fatal("LoadOpik unexpectedly accepted a holdout bundle")
	}
}

func writeJSON(t *testing.T, directory, name string, value any) {
	t.Helper()
	payload, err := json.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(directory, name), payload, 0o600); err != nil {
		t.Fatal(fmt.Errorf("write %s: %w", name, err))
	}
}
